import logging

import config
from logging_handlers import setup_telegram_logger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Set up Telegram error logger if credentials are provided
if config.common.TELEGRAM_ERROR_BOT_TOKEN and config.common.TELEGRAM_ERROR_CHAT_ID:
    setup_telegram_logger(
        config.common.TELEGRAM_ERROR_BOT_TOKEN,
        config.common.TELEGRAM_ERROR_CHAT_ID,
        level=logging.ERROR,
    )
    logger.info("Telegram error logging is enabled")
else:
    logger.warning("Telegram error logging is disabled - missing bot token or chat ID")
