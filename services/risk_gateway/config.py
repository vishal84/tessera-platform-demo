"""Risk gateway tuning. Values here are on the synchronous authorization path."""

# Fraud model response cache. Scoring the same card+amount repeatedly within a
# short window produces the same decision, so caching absorbs most of the load.
#
# This is load-bearing, not an optimisation. At a ~77% hit rate the fraud model
# sees ~96 rps against a capacity of ~155 rps. At a 0% hit rate it sees ~420 rps
# before retries, which is 2.7x capacity -- see INC-4412. Do not lower this
# without running `python -m services.risk_gateway.simulation` first.
CACHE_TTL_SECONDS = 300

# Bound the cache by entry count rather than by disabling it. Entries are also
# pruned once expired; the two together are what keep the pod's resident set
# flat (TESS-2287). Sized to cover a 5-minute window of distinct card+amount
# pairs at peak with room to spare.
CACHE_MAX_ENTRIES = 50_000

# Upstream call behaviour.
#
# The edge gives the whole authorization 8.5s. A per-attempt timeout well inside
# that is what bounds the tail: without one, a single attempt can consume the
# entire budget and the caller gives up rather than the call doing so.
REQUEST_TIMEOUT_SECONDS = 1.0
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_BASE_SECONDS = 0.05
RETRY_JITTER = True

# Connection pool to the fraud model service.
#
# NOTE: at 45ms service time the dependency saturates at ~7 concurrent calls, so
# this limit is not meaningful backpressure at any value near it. It is a
# resource bound, not a load shedder. Sizing it against dependency capacity is
# tracked as follow-up work in the INC-4412 postmortem.
MAX_CONNECTIONS = 256

# Circuit breaker.
#
# WARNING: this flag is NOT implemented in client.py -- only simulation.py and
# the ops console read it. Turning it on makes the capacity model and the health
# tile report a breaker that does not exist in the request path. Leave it False
# until the breaker is actually built; see the INC-4412 postmortem.
CIRCUIT_BREAKER_ENABLED = False
CIRCUIT_BREAKER_ERROR_THRESHOLD = 0.5
CIRCUIT_BREAKER_RESET_SECONDS = 30
