# Redis Key Convention

One shared Redis instance backs three concerns across Phases 4 and 6. It has no ACL or
per-database separation, so **key prefixes are the only thing preventing collisions** —
every writer must use consistent key-naming convention. Keys use `:` as the hierarchy separator on DB 0
(single DB).

## Prefixes

| Prefix | Purpose | Phase | TTL | Safe to lose? |
|---|---|---|---|---|
| `cache:` | Cached read models, rebuildable from Postgres | 4 | short (seconds–minutes) | yes |
| `ratelimit:` | Rate-limit counters, windowed | 4, 6 | = window length | no (see policy) |
| `ai:` | AI assistant response cache, fingerprint-keyed | 6 | ~5–10 min | yes |

## Key shapes

```
cache:cluster-health:<cluster_id>          # current health snapshot for fast frontend reads
ratelimit:ws:<ip>                          # WebSocket connections/messages per client
ratelimit:ai:global:day:<YYYY-MM-DD>       # global daily AI counter (~80% of provider limit)
ratelimit:ai:global:min:<epoch_minute>     # global per-minute AI counter
ratelimit:ai:ip:<ip>:min:<epoch_minute>    # per-IP AI counter
ai:resp:<fingerprint>                      # cached AI response; fingerprint = entity id +
                                           # health_state + unresolved failure ids (IDEA 6.1)
```

## Rules

- Always set a TTL. `cache:`/`ai:` keys expire to stay fresh; `ratelimit:` keys expire at
  the end of their window.
- Eviction policy is `noeviction`. Counters must never be silently dropped (that would let
  the AI quota be bypassed), so at the cap Redis refuses writes rather than evicting. TTL
  expiry still applies normally. At this data scale the cap is not expected to be reached.
