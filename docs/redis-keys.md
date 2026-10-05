# Redis Key Convention

A single Redis instance supports caching and rate limiting. It uses database 0 only, with no Redis ACLs or per-feature database separation. Key prefixes therefore serve as the namespace boundary: every Redis reader and writer must follow this convention exactly to prevent collisions.

All keys use `:` as the hierarchy separator.

## Namespaces

| Prefix | Purpose | TTL | Safe to lose? |
|---|---|---|---|
| `cache:` | Cached read models that can be rebuilt from PostgreSQL. | Seconds to minutes | Yes |
| `ratelimit:` | Windowed counters used to enforce connection, message, and AI usage limits. | Applicable window | No |
| `ai:` | Fingerprint-keyed cache of AI assistant responses. | ~5–10 min | Yes |

## Key Formats

```
# Current cluster-health snapshot used for low-latency frontend reads.
cache:cluster-health:<cluster_id>

# WebSocket connection counter for a client IP address.
ratelimit:websocket:<ip>

# Global daily AI request counter, capped at approximately 80% of the provider quota.
ratelimit:ai:global:day:<YYYY-MM-DD>

# Global per-minute AI request counter.
ratelimit:ai:global:min:<epoch_minute>

# Per-IP AI request counters, daily and per-minute.
ratelimit:ai:ip:<ip>:day:<YYYY-MM-DD>
ratelimit:ai:ip:<ip>:min:<epoch_minute>

# Cached AI response. The digest covers selected stable entity and related failure evidence.
ai:resp:<entity_type>:<entity_id>:<digest>
```

## Operational Rules

- Set a TTL on every key. Cache keys expire to prevent stale reads. Rate-limit keys expire when their enforcement window ends.
- Use Redis `noeviction`. Redis must reject writes when it reaches its memory limit rather than silently evicting keys.
- Never allow rate-lmiit counters to be evicted. Losing them can temporarily bypass WebSocket or AI quota enforcement.
- The configured Redis memory limit should comfortably exceed the expected dataset size. At Videre's scale, reaching the limit is not expected. Rejecting writes is nevertheless safer than weakening quota enforcement.
- WebSocket broadcasts wait at most 2 seconds per client. Busy clients skip refreshes without queuing them. The last snapshot is marked **Stale** at 20 seconds.

## AI Evidence and Invalidation

AI diagnoses include relevant failures from the requested entity, its related nodes and GPUs, and shared incidents within its cluster. Evidence is limited, and omitted details are flagged. Job metrics show overall activity; related evidence does not prove exact GPU assignment or what caused a failure.

Cached diagnoses are reused for up to seven minutes. Changes to relevant health, job placement or failures make the next request generate a fresh diagnosis. Routine telemetry and scheduler updates keep the cached answer usable until it expires, avoiding repeated AI requests as measurements change.
