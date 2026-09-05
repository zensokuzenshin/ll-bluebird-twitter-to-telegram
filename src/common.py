import logging

import config
import telemetry
from logging_handlers import setup_telegram_logger

# Must run before any handler is attached: it replaces the root handlers.
telemetry.setup_logging()

logger = logging.getLogger(__name__)

if config.common.TELEGRAM_ERROR_BOT_TOKEN and config.common.TELEGRAM_ERROR_CHAT_ID:
    setup_telegram_logger(
        config.common.TELEGRAM_ERROR_BOT_TOKEN,
        config.common.TELEGRAM_ERROR_CHAT_ID,
        level=logging.ERROR,
    )
    logger.info("Telegram error logging is enabled")
else:
    logger.warning("Telegram error logging is disabled - missing bot token or chat ID")
