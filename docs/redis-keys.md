# Redis Key Convention

Redis uses one database (`0`) for caching and rate limiting, with no custom access rules (ACLs). Key prefixes separate features and prevent collisions.

All keys use `:` as the hierarchy separator.

## Namespaces

TTL is how long a key lasts before it expires.

| Prefix | Purpose | TTL | Safe to lose? |
|---|---|---|---|
| `cache:` | Cached data that can be rebuilt from PostgreSQL. | 20 seconds by default | Yes |
| `ratelimit:` | WebSocket connection counts and AI request counters. | AI window; WebSocket: one hour on connection attempts | No |
| `ai:` | Cached AI assistant responses. | Seven minutes by default | Yes |

## Key Formats

```
# Current cluster-health snapshot used for low-latency frontend reads.
cache:cluster-health:<cluster_id>

# WebSocket connection counter for the client IP seen by the backend.
ratelimit:websocket:<ip>

# Global daily AI request counter, configured for 400 requests per UTC day.
ratelimit:ai:global:day:<YYYY-MM-DD>

# Global per-minute AI request counter.
ratelimit:ai:global:min:<epoch_minute>

# Per-IP AI request counters, using the client IP seen by the backend.
ratelimit:ai:ip:<ip>:day:<YYYY-MM-DD>
ratelimit:ai:ip:<ip>:min:<epoch_minute>

# Cached AI response. The digest covers selected stable entity and related failure evidence.
ai:resp:<entity_type>:<entity_id>:<digest>
```

## Operational Rules

- Cache keys expire to prevent stale reads. AI counters expire at the end of their minute or UTC day. WebSocket connection attempts refresh a one-hour TTL.
- WebSocket disconnect cleanup can reset a counter to zero without a TTL. This is a current implementation gap.
- AI counters apply to cache misses; cached responses bypass the limits.
- Use `noeviction` and allow enough memory for the expected data. Redis then rejects writes at its memory limit; removing rate-limit counters could bypass quotas.
- WebSocket broadcasts send to clients concurrently and wait up to two seconds. Clients with a send still in progress skip later refreshes. The last snapshot is marked **Stale** at 20 seconds.

## AI Evidence and Invalidation

AI diagnoses use relevant failures from the requested entity, related nodes and GPUs, and shared cluster incidents. Omitted details are flagged. Job metrics show overall activity, not exact GPU assignments or proof of a failure's cause.

Cached diagnoses last up to seven minutes by default. Relevant health, job placement, or failure changes stop reuse; routine telemetry and scheduler updates do not.
