# Task Cache Design

## Problem

The Morgen `list_tasks` endpoint costs 10 rate limit points per request. In conversational usage ("list my tasks" followed by "which are due today?" followed by "what lists do I have?"), each follow-up burns another 10 points against the same data. This leads to 429 rate limit errors during normal usage.

## Design

Client-level in-memory response cache for `list_tasks` with a 5-minute TTL.

### Cache behavior

- **TTL:** 300 seconds (5 minutes)
- **Cache key:** `("list_tasks", updated_after)` — different `updated_after` values get separate cache entries
- **Invalidation:** Any task write operation (`create_task`, `update_task`, `delete_task`, `close_task`, `reopen_task`, `move_task`) clears the entire tasks cache immediately
- **Transparent:** No `use_cache` parameter exposed to the LLM. The cache just works.
- **Rate limit fallback:** When a 429 hits on `list_tasks`, return stale cached data (if available) with a `_cached` flag instead of erroring
- **Scope:** In-memory, session-scoped. No persistence across server restarts.

### What is NOT cached

- `get_task` — cheap call, users expect fresh data for a specific task
- Events, calendars, accounts — different endpoints, out of scope

### Data flow

```
list_tasks()  →  cache miss  →  API call  →  store in cache  →  return
list_tasks()  →  cache hit (< 5min)  →  return cached  (no API call)
close_task()  →  API call  →  clear cache
list_tasks()  →  cache miss  →  API call  →  store in cache  →  return
list_tasks()  →  429 + stale cache exists  →  return stale with _cached flag
```

### Files to change

1. **`client.py`** — Add `_task_cache` dict and `_TASK_CACHE_TTL` to `MorgenClient`. Cache logic in `list_tasks`. Cache-clear in all task write methods.
2. **`tools/tasks.py`** — Catch 429 in `list_tasks`/`list_task_lists`, try stale cache before raising. Add `_cached` flag to response when serving from cache. Update docstrings.
3. **Tests** — Cache hit, miss, invalidation, TTL expiry, stale-on-429.

### Trade-offs

- **Pro:** Eliminates redundant API calls in conversational patterns (most common usage)
- **Pro:** Graceful degradation on rate limits instead of hard errors
- **Con:** Data can be up to 5 minutes stale (acceptable per user preference)
- **Con:** Write-then-read from a different client instance won't see invalidation (single-process only)
