"""Risk gateway tuning. Values here are on the synchronous authorization path."""

# Fraud model response cache. Scoring the same card+amount repeatedly within a
# short window produces the same decision, so caching absorbs most of the load.
CACHE_TTL_SECONDS = 300

# Upstream call behaviour.
REQUEST_TIMEOUT_SECONDS = None
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SECONDS = 0.0
RETRY_JITTER = False

# Connection pool to the fraud model service.
MAX_CONNECTIONS = 512

# Circuit breaker. Disabled -- never got prioritised.
CIRCUIT_BREAKER_ENABLED = False
CIRCUIT_BREAKER_ERROR_THRESHOLD = 0.5
CIRCUIT_BREAKER_RESET_SECONDS = 30
