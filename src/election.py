"""Leader election backed by a Kubernetes Lease (coordination.k8s.io/v1).

Only the leader polls Twitter, so the Deployment can run more than one replica
without double-posting. Replaces a ConfigMap lock: a Lease exists purely to
carry the lock, so renewals no longer rewrite application config, and the RBAC
needed is on `coordination.k8s.io/leases` rather than on `configmaps`.
"""

import asyncio
import os
import socket
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from kubernetes_asyncio import client
from kubernetes_asyncio import config as kube_config
from kubernetes_asyncio.leaderelection import electionconfig, leaderelection
from kubernetes_asyncio.leaderelection.resourcelock.leaselock import LeaseLock

import config as app_config
import telemetry
from common import logger

# Hostname keeps `kubectl get lease` readable; the suffix disambiguates if two
# candidates ever share one.
candidate_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

LeaderTask = Callable[[], Coroutine[Any, Any, None]]

_MAX_BACKOFF = 60.0

# Below this, a run of failed lock reads is ordinary churn — a rollout, an API
# server blip, an RBAC change landing. Above it, this replica is stuck.
_LOCK_FAILURE_ALERT_AFTER = 5


class _ObservedLeaseLock(LeaseLock):
    """A LeaseLock that escalates a persistent inability to read the lease.

    `LeaderElection.acquire()` swallows lock errors and retries forever, so a
    replica denied RBAC on leases sits as a silent non-leader with nothing for
    `run_forever` to catch. Count consecutive failures and complain once, at a
    level that reaches the error channel, instead of per retry.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._failures = 0

    async def get(self, name: str, namespace: str):
        found, record = await super().get(name, namespace)

        # A 404 is normal: nobody has created the lease yet.
        if found or getattr(record, "status", None) == 404:
            if self._failures >= _LOCK_FAILURE_ALERT_AFTER:
                logger.warning(
                    "Lease %s readable again after %d failures", name, self._failures
                )
            self._failures = 0
        else:
            self._failures += 1
            if self._failures == _LOCK_FAILURE_ALERT_AFTER:
                logger.error(
                    "Cannot read lease %s after %d attempts (%s); this replica "
                    "cannot take leadership",
                    name,
                    self._failures,
                    getattr(record, "reason", record),
                )

        return found, record


def _timings() -> tuple[int, float, float]:
    """Lease duration, renew deadline and retry period, in seconds.

    The 15/10/2 ratio controller-runtime defaults to, scaled to the configured
    TTL so `lease > renew > 1.2 * retry` still holds. The duration stays a
    whole number because `leaseDurationSeconds` is an integer field.
    """
    lease_duration = int(app_config.common.LEADER_ELECTION_LEASE_TTL)
    return (
        lease_duration,
        lease_duration * 2 / 3,
        max(1.0, lease_duration * 2 / 15),
    )


async def _lead(leader_task: LeaderTask) -> None:
    """Run the leader-only work; cancelled by the election once the lease goes."""
    logger.info(
        "Acquired lease %s as %s",
        app_config.common.LEADER_ELECTION_LOCK_NAME,
        candidate_id,
    )
    telemetry.set_leader(True)
    try:
        await leader_task()
    except asyncio.CancelledError:
        raise
    except Exception:
        # Nothing awaits this task, so an unhandled error would otherwise only
        # surface when the garbage collector complained.
        logger.exception("Leader task stopped with an error")


async def _on_stopped_leading() -> None:
    telemetry.set_leader(False)
    logger.warning(
        "Lost lease %s; standing by to re-acquire",
        app_config.common.LEADER_ELECTION_LOCK_NAME,
    )


async def _stop_leading(tasks: set[asyncio.Task[None]]) -> None:
    """Cancel the leader tasks and wait for them, so none outlives its election."""
    pending = [task for task in tasks if not task.done()]
    # Requested on all of them before awaiting any, so a cancellation delivered
    # to us midway still leaves every one of them tearing down.
    for task in pending:
        task.cancel()
    if pending:
        # return_exceptions: _lead has already logged anything worth seeing, and
        # one task's error must not hide another's teardown.
        await asyncio.gather(*pending, return_exceptions=True)
    tasks.difference_update(pending)


async def _contend_once(
    api: client.ApiClient,
    leader_task: LeaderTask,
    leading: set[asyncio.Task[None]],
) -> None:
    """Wait for the lease, hold it, return once it is lost.

    `LeaderElection.run()` starts the leader task itself and only cancels it if
    `renew_loop()` *returns* (leaderelection.py:70-77). When the renewal raises
    instead — the apiserver refusing a connection is enough — that cancel is
    skipped, the task is orphaned, and `run_forever` starts a fresh election on
    top of a poll loop that is still running. Every such blip used to add one
    more concurrent poller against a metered API. So the task registers itself
    in `leading` and every exit path here cancels whatever is left.
    """
    lease_duration, renew_deadline, retry_period = _timings()

    async def lead() -> None:
        task = asyncio.current_task()
        if task is not None:
            leading.add(task)
        await _lead(leader_task)

    election = leaderelection.LeaderElection(
        electionconfig.Config(
            _ObservedLeaseLock(
                app_config.common.LEADER_ELECTION_LOCK_NAME,
                app_config.common.LEADER_ELECTION_NAMESPACE,
                candidate_id,
                api,
            ),
            lease_duration=lease_duration,
            renew_deadline=renew_deadline,
            retry_period=retry_period,
            onstarted_leading=lead,
            onstopped_leading=_on_stopped_leading,
        )
    )
    try:
        await election.run()
    finally:
        await _stop_leading(leading)


async def run_forever(leader_task: LeaderTask) -> None:
    """Contend for leadership for as long as the process lives.

    `LeaderElection.run()` returns as soon as one renewal fails, so it has to
    be restarted; otherwise a single missed renewal leaves the replica a
    permanent follower doing nothing.
    """
    if not app_config.common.LEADER_ELECTION:
        logger.info("Leader election disabled; running the leader task directly.")
        telemetry.set_leader(True)
        await leader_task()
        return

    # Explicit rather than load_config(), which warns about a missing
    # ~/.kube/config on the way to picking the in-cluster credentials.
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        kube_config.load_incluster_config()
    else:
        await kube_config.load_kube_config()

    _, _, retry_period = _timings()
    backoff = retry_period

    # Shared across rounds, so a task that registers itself just as one election
    # unwinds is still cancelled by the next round's cleanup.
    leading: set[asyncio.Task[None]] = set()

    async with client.ApiClient() as api:
        while True:
            try:
                try:
                    await _contend_once(api, leader_task, leading)
                finally:
                    # _on_stopped_leading covers a clean loss; this also covers
                    # the election erroring out while we were still leader.
                    telemetry.set_leader(False)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Leader election failed; retrying in %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)
            else:
                backoff = retry_period
