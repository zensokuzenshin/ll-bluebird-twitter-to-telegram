import asyncio
import html
import logging
import socket
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_MAX_CHARS = 4096
_TRUNCATION_NOTE = "\n[message truncated due to length]"

# Telegram starts answering 429 well below a per-second error rate, and the
# flood only lengthens the cooldown. The hundredth copy of a traceback says
# nothing the first one did not, so spend a budget per window and report the
# rest as a count.
_MAX_PER_WINDOW = 10
_WINDOW_SECONDS = 60.0

# Loggers that report retryable churn at ERROR, once per retry. Losing a lease
# update race (409) is how leader election is *supposed* to work, and a failed
# span export fixes itself. Both still reach stdout and Loki; election.py
# escalates the failures that turn out to be persistent.
_MUTED_LOGGERS = (
    "opentelemetry.",
    "kubernetes_asyncio.leaderelection.",
)


class TelegramLogHandler(logging.Handler):
    """
    A custom logging handler that sends log messages to a Telegram chat.
    Only sends ERROR level messages and above, at a bounded rate.
    """

    def __init__(self, bot_token: str, chat_id: str, level=logging.ERROR):
        super().__init__(level)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.hostname = socket.gethostname()
        self.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        # asyncio only holds a weak reference to a running task, so without
        # this the sends could be garbage collected before they finish.
        self._pending: set[asyncio.Task] = set()
        self._window_started = time.monotonic()
        self._sent = 0
        self._dropped = 0

    def _within_budget(self) -> bool:
        """Fixed-window rate limit; reports the drops as each window rolls over."""
        now = time.monotonic()
        if now - self._window_started >= _WINDOW_SECONDS:
            dropped, self._dropped = self._dropped, 0
            self._window_started = now
            self._sent = 0
            if dropped:
                self._dispatch(
                    f"{dropped} further error(s) suppressed "
                    f"in the last {int(_WINDOW_SECONDS)}s"
                )

        if self._sent >= _MAX_PER_WINDOW:
            self._dropped += 1
            return False

        self._sent += 1
        return True

    def emit(self, record):
        """Send the log record to Telegram, from either a sync or async caller."""
        if record.levelno < self.level or record.name.startswith(_MUTED_LOGGERS):
            return
        if not self._within_budget():
            return

        self._dispatch(self.format(record))

    def _dispatch(self, text: str) -> None:
        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No loop in this thread; run the send to completion.
                asyncio.run(self._async_send(text))
                return

            task = asyncio.create_task(self._async_send(text))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

        except Exception as e:
            # Never let logging take the process down
            print(f"Error sending log to Telegram: {e}")

    def _as_html(self, text: str) -> str:
        """HTML rather than Markdown: tracebacks routinely contain characters
        Markdown cannot represent, and each one used to cost a 400 plus a second
        POST to retry without formatting. `html.escape` has no such gaps."""
        return (
            f"🚨 <b>Error on {html.escape(self.hostname)}</b>\n\n"
            f"<pre>{html.escape(text)}</pre>"
        )

    def _truncate(self, text: str) -> str:
        """Trim so the escaped, wrapped message still fits Telegram's limit.

        Escaping expands the text, so it is the raw string that gets cut here:
        slicing the escaped one could split an entity like `&amp;` in half.
        """
        budget = _TELEGRAM_MAX_CHARS - len(self._as_html("")) - len(_TRUNCATION_NOTE)
        if len(html.escape(text)) <= budget:
            return text

        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if len(html.escape(text[:mid])) <= budget:
                low = mid
            else:
                high = mid - 1
        return text[:low] + _TRUNCATION_NOTE

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.post(url, json=payload)

    async def _async_send(self, text: str) -> dict[str, Any]:
        text = self._truncate(text)
        payload = {
            "chat_id": self.chat_id,
            "text": self._as_html(text),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            response = await self._post(payload)

            if response.status_code == 400:
                # A last resort now that the payload is escaped, rather than the
                # routine second half of every send. Only for 400: re-posting a
                # 429 straight away is precisely what earned it.
                print(f"Failed to send log to Telegram: {response.text}")
                payload["parse_mode"] = None
                payload["text"] = f"Error on {self.hostname}\n\n{text}"
                response = await self._post(payload)
            elif response.status_code != 200:
                print(f"Failed to send log to Telegram: {response.text}")

            return response.json()

        except Exception as e:
            # Deliberately printed rather than logged: logging from inside a
            # log handler would recurse straight back into here.
            print(f"Error sending log to Telegram: {e}")
            return {"ok": False, "error": str(e)}


def setup_telegram_logger(
    bot_token: str, chat_id: str, level=logging.ERROR, test=False
):
    """Route errors and above to a Telegram chat."""
    logging.getLogger().addHandler(TelegramLogHandler(bot_token, chat_id, level))
    logger.info("Telegram error logger has been configured")

    if test:
        logger.error("This is a test error message from the Telegram logger setup")
