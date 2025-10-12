import asyncio
import uuid

from kubernetes_asyncio import client
from kubernetes_asyncio import config as kube_config
from kubernetes_asyncio.leaderelection import electionconfig, leaderelection
from kubernetes_asyncio.leaderelection.resourcelock.configmaplock import ConfigMapLock

import config as app_config
from common import logger

candidate_id = str(uuid.uuid4())

is_leader = False
leader_lock = asyncio.Lock()


async def on_started_leading():
    global is_leader
    async with leader_lock:
        is_leader = True
    logger.info(f"{candidate_id} has become the leader.")


async def on_stopped_leading():
    global is_leader
    async with leader_lock:
        is_leader = False
    logger.info(f"{candidate_id} has lost leadership.")


async def start_election():
    if not app_config.common.LEADER_ELECTION:
        logger.info("Leader election is disabled. Running as leader.")
        await on_started_leading()
        return

    await kube_config.load_config()
    async with client.ApiClient() as api:
        election_config = electionconfig.Config(
            ConfigMapLock(
                app_config.common.LEADER_ELECTION_LOCK_NAME,
                app_config.common.LEADER_ELECTION_NAMESPACE,
                candidate_id,
                api,
            ),
            lease_duration=app_config.common.LEADER_ELECTION_LEASE_TTL,
            renew_deadline=min(
                app_config.common.LEADER_ELECTION_LEASE_TTL * 0.8,
                app_config.common.LEADER_ELECTION_LEASE_TTL - 3,
            ),
            retry_period=5,
            onstarted_leading=on_started_leading,
            onstopped_leading=on_stopped_leading,
        )
        await leaderelection.LeaderElection(election_config).run()
