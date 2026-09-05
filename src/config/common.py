import os

# API configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# The accounts post in bursts, so poll closer while one is running
TWITTER_QUERY_INTERVAL_ORDINARY = int(
    os.getenv("TWITTER_QUERY_INTERVAL_ORDINARY", "900")
)
TWITTER_QUERY_INTERVAL_ON_MESSAGE = int(
    os.getenv("TWITTER_QUERY_INTERVAL_ON_MESSAGE", "300")
)
TWITTER_QUERY_INTERVAL_ON_ERROR = int(
    os.getenv("TWITTER_QUERY_INTERVAL_ON_ERROR", "60")
)

# Comma-separated "provider:model" entries, tried in order until one succeeds
DEFAULT_TRANSLATION_MODELS = "anthropic:claude-sonnet-5"
TRANSLATION_MODELS = [
    model.strip()
    for model in os.getenv("TRANSLATION_MODELS", DEFAULT_TRANSLATION_MODELS).split(",")
    if model.strip()
]

# Error logging configuration
TELEGRAM_ERROR_BOT_TOKEN = os.getenv("TELEGRAM_ERROR_BOT_TOKEN")
TELEGRAM_ERROR_CHAT_ID = os.getenv("TELEGRAM_ERROR_CHAT_ID")

# PostgreSQL configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "twitter_telegram")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DSN = os.getenv(
    "POSTGRES_DSN",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)

# The lock is a coordination.k8s.io Lease, so the ServiceAccount needs
# get/create/update on leases in LEADER_ELECTION_NAMESPACE.
LEADER_ELECTION = os.getenv("LEADER_ELECTION", "false").lower() in ("true", "1", "yes")
LEADER_ELECTION_LOCK_NAME = os.getenv(
    "LEADER_ELECTION_LOCK_NAME", "ll-bluebird-dev-lock"
)
LEADER_ELECTION_NAMESPACE = os.getenv("LEADER_ELECTION_NAMESPACE", "default")
LEADER_ELECTION_LEASE_TTL = int(os.getenv("LEADER_ELECTION_LEASE_TTL", "30"))  # seconds
