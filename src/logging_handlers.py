import logging
import asyncio
import httpx
from typing import Dict, Any
import socket

# Configure module-specific logger
logger = logging.getLogger(__name__)


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
        self.loop = None
        self.formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    def emit(self, record):
        """
        Send the log record to Telegram.
        Uses an event loop to handle async operations from a synchronous context.
        """
        if record.levelno < self.level:
            return

        # Get the formatted log message
        msg = self.format(record)

        # Add error traceback if available
        if record.exc_info:
            # Use logging's formatException instead of our own
            exc_text = self.formatter.formatException(record.exc_info)
            msg += "\n\n" + exc_text

        # Enhance with hostname information
        msg = f"🚨 *Error on {self.hostname}*\n\n```\n{msg}\n```"

        # Run the async send operation
        self._send_to_telegram(msg)

    def _send_to_telegram(self, message: str):
        """Call the async function from the synchronous emit method"""
        # We need to make sure the message gets sent, even in a sync context
        try:
            # Try to get the current running loop, if any
            try:
                loop = asyncio.get_running_loop()
                # We're already in a loop, create a task
                if loop.is_running():
                    asyncio.create_task(self._async_send(message))
                    return
            except RuntimeError:
                # No loop running, we'll create one
                pass

            # No existing loop, run in new event loop
            asyncio.run(self._async_send(message))

        except Exception as e:
            # If anything goes wrong, log it but don't crash
            print(f"Error sending log to Telegram: {str(e)}")

    async def _async_send(self, message: str) -> Dict[str, Any]:
        """Asynchronously send a message to the Telegram chat."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        # Ensure message is not too long for Telegram (max 4096 chars)
        if len(message) > 4000:
            message = message[:3900] + "...\n[message truncated due to length]"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            # Set a timeout for the request
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)

            if response.status_code != 200:
                print(f"Failed to send log to Telegram: {response.text}")
                logger.error(f"Failed to send log to Telegram: {response.text}")

                # If parse_mode causes an issue, try without it
                if "parse mode" in response.text.lower():
                    print("Retrying without Markdown parsing...")
                    payload["parse_mode"] = None
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.post(url, json=payload)

                    if response.status_code == 200:
                        print("Successfully sent message without Markdown parsing")
                        return response.json()
            else:
                return response.json()

        except Exception as e:
            error_msg = f"Error sending log to Telegram: {str(e)}"
            print(error_msg)
            logger.error(error_msg)

            # Try one more time without markdown parsing
            try:
                payload["parse_mode"] = None
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(url, json=payload)
                return response.json()
            except Exception as e2:
                print(f"Second attempt failed: {str(e2)}")

            return {"ok": False, "error": str(e)}


def setup_telegram_logger(
    bot_token: str, chat_id: str, level=logging.ERROR, test=False
):
    """
    Set up a Telegram logger that sends messages for errors and above.

    Args:
        bot_token: The Telegram bot token to use
        chat_id: The Telegram chat ID to send messages to
        level: The minimum log level to send (default: ERROR)
        test: Whether to send a test message (default: False)
    """
    # Create the handler
    handler = TelegramLogHandler(bot_token, chat_id, level)

    # Set the formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)

    # Add the handler to the root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    # Log info message
    logger.info("Telegram error logger has been configured")

    # Send a test message if requested
    if test:
        logger.error("This is a test error message from the Telegram logger setup")
        logger.info("A test error message was sent to Telegram")
