import asyncio
import logging
import socket
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_MAX_CHARS = 4096
_TRUNCATED_AT = 3900

# Telemetry export failures are logged at ERROR and retried; they are an infra
# problem visible in the pod logs, not something to page a Telegram chat about.
_MUTED_LOGGERS = ("opentelemetry.",)


class TelegramLogHandler(logging.Handler):
    """
    A custom logging handler that sends log messages to a Telegram chat.
    Only sends ERROR level messages and above.
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

    def emit(self, record):
        """Send the log record to Telegram, from either a sync or async caller."""
        if record.levelno < self.level or record.name.startswith(_MUTED_LOGGERS):
            return

        message = f"🚨 *Error on {self.hostname}*\n\n```\n{self.format(record)}\n```"

        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No loop in this thread; run the send to completion.
                asyncio.run(self._async_send(message))
                return

            task = asyncio.create_task(self._async_send(message))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

        except Exception as e:
            # Never let logging take the process down
            print(f"Error sending log to Telegram: {e}")

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.post(url, json=payload)

    async def _async_send(self, message: str) -> dict[str, Any]:
        if len(message) > _TELEGRAM_MAX_CHARS:
            message = message[:_TRUNCATED_AT] + "...\n[message truncated due to length]"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            response = await self._post(payload)

            if response.status_code != 200:
                # Tracebacks regularly contain characters Markdown chokes on;
                # the message matters more than the formatting.
                print(f"Failed to send log to Telegram: {response.text}")
                payload["parse_mode"] = None
                response = await self._post(payload)

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
