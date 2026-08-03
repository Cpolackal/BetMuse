# BetMuse

Predictive analytics platform for ATP tennis markets on Kalshi. Ingests live market data via WebSocket, joins it against a live tennis score feed, computes a model-based fair price, fires signal alerts, and persists snapshots to PostgreSQL. A React frontend shows a live landing page of upcoming matches, per-market analytics charts, a live scoreboard, and a model-vs-market price overlay.

## Architecture Overview

The backend is a single async Python process that runs several cooperative coroutines. All coordination between them uses shared in-memory state (`active_markets`, and the `app/core/live_state.py` singletons) and Redis Streams (`ticks`, `scores`, `alerts`).

```
Kalshi WS  ──►  ws_loop  ──►  Redis Stream "ticks"
                                    │
                   ┌────────────────┼──────────────────┐
                   ▼                ▼                   ▼
           buffer_maintainer   alert_engine         db_writer
           (group: buffer_maintainer) (group: alert_engine)  (timer-based)
                   │                │  ▲                │
           active_markets       active_markets           │
                                    │  │                  │
                          live_state.match_states/    live_state.model_prices/
                          market_links (read)          match_states/market_links (read)
                                    ▲
                                    │
                              score_feed (timer, polls SofaScore)
                                    │
                               backstop (timer, resolves closed markets, purges old ones)
```

**Entry point:** `app/runner.py::run_websocket_client` — creates Redis consumer groups and gathers all coroutines.

**FastAPI app:** `app/main.py` — starts `run_websocket_client` as a background task when `KALSHI_WS_RUN=1`.

**Frontend:** `frontend/src/App.jsx` — single-file React app (Vite), inline styles, no router. Landing page shows live upcoming ATP matches; selecting one shows a full detail view (score panel, alerts, analytics charts with a model-price overlay).

## Workers

| Worker | File | How triggered | Purpose |
|---|---|---|---|
| `ws_loop` | `app/websockets/client.py` | Continuous WS stream | Connects to Kalshi, deserializes ticker_v2 messages, computes analytics, writes `Tick` objects to Redis stream `ticks` |
| `buffer_maintainer` | `app/workers/buffer_maintainer.py` | Redis consumer group `buffer_maintainer` | Creates/updates per-market `contract_buffer` in `active_markets`; on first-seen market, fetches metadata from Kalshi REST and upserts `market_meta` via `set_market` |
| `alert_engine` | `app/workers/alert_engine.py` | Redis consumer group `alert_engine` | Reads ticks, runs detectors against the in-memory buffer tail, writes fired signals to Redis stream `alerts` (maxlen 10000); 30s per-market cooldown; suppresses all detectors while the 25-tick window straddles a >45s arrival gap (tennis changeover/set break), using stream-ID timestamps. Joins ticks to `match_states` via `market_links` for the `model_divergence` detector, and publishes a `model_prices` entry (`app/core/live_state.py`) on every tick it evaluates — not just when an alert fires — so the frontend and `db_writer` always have a current model price to read |
| `db_writer` | `app/workers/db_writer.py` | `asyncio.sleep(5)` interval | Snapshots the latest tick from each dirty buffer to `market_snapshots` via `bulk_insert_ticks`, stamping `model_price` (from `live_state.model_prices`) and `score_state` (compact JSON from `live_state.match_states`, via `market_links`) onto each row when available |
| `score_feed` | `app/workers/score_feed.py` | `asyncio.sleep(5)` interval | Polls SofaScore live tennis feed (via `curl_cffi` browser TLS impersonation — plain HTTP clients get 403), keeps `live_state.match_states: dict[event_id, MatchState]` current, resolves market tickers to `(event_id, side)` in `live_state.market_links` by querying SofaScore's event search with both surnames from the Kalshi title (SofaScore does the name resolution), then verifying via `app/services/match_mapper.py`: both surnames must match the event's players and the ticker-embedded date must agree with the event start time (search returns historical head-to-heads); refuses ambiguous matches (returns None, retried after 60s). Mapping can resolve before a match goes live. Reconstructs point-by-point outcomes by diffing consecutive polls (only when unambiguous — same game, same server, non-tiebreak) to maintain `MatchState.serve_played`/`serve_won` in-play serve stats. Publishes state changes to Redis stream `scores` (maxlen 10000) and a `match_events` DB row per change; upserts `market_links` rows to Postgres and preloads them on startup (scoped to currently-active tickers) |
| `backstop` | `app/workers/backstop.py` | `asyncio.sleep(1800)` interval | Resolves markets and purges old data — see **Data Retention** below |

## Core Data Types

**`Tick`** (`app/core/contract_buffer.py`) — Pydantic model, the canonical per-tick data unit. Fields: `market`, `price`, `bid`, `ask`, `spread`, `volume_1s/10s/60s`, `imbalance`, `momentum`, `last_trade_ts`, and optional `no_bid/ask`, `liquidity`, `open_interest`, `dollar_volume/open_interest`, `bid_size`, `ask_size`, `last_trade_size`.

**`MatchState`** (`app/core/match_state.py`) — Pydantic model of a live tennis match from the score feed: `home/away` names, `set_games` per set, current-game `points`, derived `serving` (1=home, 2=away, from game parity + `firstToServe`), `tiebreak`, `best_of`, `status`, and in-play `serve_played`/`serve_won` counters (each `(home, away)` tuples, maintained by `score_feed`'s point-diffing — see below). Keyed by SofaScore event id in `live_state.match_states`. `compact_json()` produces the small score-only payload stored in `market_snapshots.score_state`.

**`live_state`** (`app/core/live_state.py`) — process-wide singletons shared between the runner's workers and the FastAPI routes (same process, so a module dict suffices): `match_states: dict[event_id, MatchState]`, `market_links: dict[ticker, (event_id, side)]`, `model_prices: dict[ticker, dict]` (`model_price`, `market_price`, `edge`, `pa`, `pb`, `ts`).

**`contract_buffer`** (`app/core/contract_buffer.py`) — Rolling deque (maxlen=600 ticks) per market. Tracks `last_seen` (monotonic) and `last_written` to drive the db_writer dirty check. `tail(n)` returns the last n ticks as a list.

## Tennis Win-Probability Model (`app/services/tennis_model.py`)

Closed-form O'Malley recursion: game-win probability from any point score (exact deuce formula), tiebreak from any score (with serve rotation), set from any game score, match from any set score — composed into `match_win_probability(MatchState, pa, pb)`, the home-side win probability from a live scoreboard. `pa`/`pb` are each player's probability of winning a point on their own serve.

**Calibration**: `calibrate_serve_points` bisects the serve-skew around the tour-average 0.645 until the model's price matches the market's at the first eligible tick after a market maps to a live match — this bakes in any market mispricing at that instant as the model's prior, and needs no external player stats.

**In-play update** (`alert_engine._posterior_serve_points`): the calibrated `(pa, pb)` is a Beta-Binomial prior; each tick, it's blended with the match's own in-play `serve_played`/`serve_won` counts (pseudo-count `SERVE_PRIOR_WEIGHT = 100`, roughly a match's worth of points before real data dominates the prior). This is what actually drives the model price shown to users and used by the divergence detector — not the fixed calibrated value.

## Detectors (`app/services/detectors.py`)

All detectors take a `window: list[Tick]` (typically the last 25 ticks). Each computes `recent - baseline` where baseline = mean of first 10 items and recent = mean of last 5 items.

| Detector | Signal | Threshold |
|---|---|---|
| `microprice_delta` | Size-weighted mid (bid×ask_size + ask×bid_size) / (bid_size+ask_size) shift | ±0.02 |
| `volume_spike` | `volume_10s` delta | ±100 |
| `imbalance_shift` | `(bid-ask)/(bid+ask)` delta | ±0.1 |
| `spread_compression` | `spread` delta | ±0.01 |
| `liquidity_drain` | `liquidity` delta | ≤ -5.0 |

**`model_divergence`** (in `alert_engine`, not `detectors.py`): for markets with a score-feed link, compares market mid to the tennis model's price (using the in-play-updated `pa`/`pb`, see above). Fires when |mid − model| ≥ 0.04 for 5 consecutive ticks; payload adds `model_price`/`market_price` fields, which `app/routes/alerts/route.py` passes through on the SSE stream when present.

Alert payloads go to Redis stream `alerts` with fields: `market`, `type`, `direction`, `value`, `ts`, and optionally `model_price`/`market_price`.

## Backtesting (`scripts/backtest_divergence.py`)

Standalone script (`python scripts/backtest_divergence.py`, run from repo root). Loads `market_snapshots` rows with a non-null `model_price`, computes `edge = mid - model_price` as a time series per ticker, then for a sweep of thresholds (0.02–0.08) × persistence values (3–10 ticks) replays `alert_engine`'s streak logic offline and measures, for each simulated signal, whether `|edge|` actually shrank 1/5/15 minutes later (nearest snapshot within a 90s tolerance). Outputs a sorted table of signal count / hit rate / mean decay per combo — this is the tool for deciding whether `MODEL_EDGE_THRESHOLD`/`MODEL_EDGE_PERSIST` in `alert_engine.py` should change. `--ticker-prefix` and `--min-signals` flags scope the run.

## Analytics Pipeline (`app/services/market_analytics.py`)

`compute_market_analytics(ticker, msg)` transforms a raw Kalshi `ticker_v2` WebSocket message into the analytics dict consumed by `Tick`. Maintains a per-process `markets_history` deque (in-module global) for sliding-window volume and momentum computation. History is trimmed to 60 seconds. Prices are in dollars (Kalshi sends `price_dollars`, `yes_bid_dollars`, `yes_ask_dollars`).

## Database Schema

Managed by Alembic (`alembic upgrade head`). Four tables:

**`market_meta`** — one row per market ticker. Fields: `ticker` (unique), `event_ticker`, `series_ticker`, `title`, `open_time`, `close_time`, `result` (nullable bool). Indexed on `ticker`, `event_ticker`, `series_ticker`.

**`market_snapshots`** — time-series snapshots. Fields: `ticker`, `snapshot_time`, `last_price`, `yes_bid/ask`, `no_bid/ask`, `open_interest`, `liquidity`, `bid_size`, `ask_size`, `last_trade_size`, `last_trade_ts`, `model_price` (nullable), `score_state` (nullable, compact JSON). Compound index on `(ticker, snapshot_time)`.

**`match_events`** — one row per score change (`event_id`, `ts`, `state_json`), written by `score_feed`. Keyed by tennis event id, not Kalshi ticker, so it outlives any one market — kept even after `market_meta`/`market_snapshots` rows for that match are purged.

**`market_links`** — persisted ticker↔event mapping (`ticker` unique, `event_id`, `side`, `home`, `away`, `linked_at`), mirrors `live_state.market_links` so mappings survive a restart without re-running SofaScore search.

## Data Retention (`backstop`, `app/db/crud.py`)

**Important gotcha**: Kalshi's `close_time` is the market's outer trading-window deadline — often ~2 weeks after the actual match (the market stays open for settlement/disputes). It is **not** a signal that the match is over. Anything gated on `close_time` will treat a long-finished match as still active for two weeks. Everything below is gated on `open_time` (the actual scheduled match start) instead.

- **`get_unresolved_markets`**: markets `backstop` checks against Kalshi's live `/markets/{ticker}` endpoint (via `fetch_market` — *not* `/historical/markets/{ticker}`, which 404s for tickers that are only resolved-in-place, not archived) for a settlement result. Gated on `open_time < now() - 3h`, so a match is checked starting a few hours after it plausibly finished; a still-unresolved fetch just retries next 30-min cycle.
- **`get_upcoming_markets`** (landing page): unresolved markets with `open_time > now() - 8h` — excludes long-finished matches still awaiting resolution, without hiding a slow live match.
- **`search_markets`**: resolved markets are always searchable (bounded by the purge below); unresolved ones are excluded once `open_time` is more than a day in the past, so a market `backstop` hasn't caught up to yet doesn't linger in search indefinitely.
- **`purge_resolved_markets`**: deletes `market_meta` + `market_snapshots` + `market_links` rows for markets resolved more than a day ago. `match_events` is not touched (see above).
- **`purge_snapshots`**: a flat 7-day snapshot purge, as a safety net for markets that never resolve (stuck/orphaned) — bounded, not the primary retention mechanism.

## Authentication

Kalshi WebSocket auth uses RSA-PSS signatures. `app/websockets/socket_auth.py` signs `{timestamp_ms}GET/trade-api/ws/v2` with a PEM private key and returns three headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, `KALSHI-ACCESS-TIMESTAMP`.

REST API calls (market fetch, historical) are unauthenticated public endpoints.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `KALSHI_API_KEY` | Yes (WS) | Kalshi API key |
| `KALSHI_PRIVATE_KEY_PATH` | No | Path to PEM key file (default: `keys/kalshi-socket.pem`) |
| `KALSHI_WS_RUN` | No | Set to `1`/`true`/`yes` to start the WS client on FastAPI startup |
| `TICKER_ALLOW_PREFIXES` | No | Comma-separated market-ticker prefixes to ingest (e.g. `KXATPMATCH` for ATP tennis). Unset = all markets. Applied in `ws_loop` (before ticks hit the Redis stream), the seeder, and the `/markets/` and `/markets/upcoming` routes. |

## Running Locally

```bash
# Infrastructure + backend (Dockerfile-based, mounted volume, --reload)
docker compose up -d

# With WS enabled, set KALSHI_WS_RUN=1 in .env, or run uvicorn directly:
KALSHI_WS_RUN=1 uvicorn app.main:app --reload

# Frontend (Vite + React 19)
cd frontend && npm run dev   # http://localhost:5173

# Migrations
DATABASE_URL=... alembic upgrade head

# Backtest
DATABASE_URL=... python scripts/backtest_divergence.py
```

## Key Design Decisions

- **Shared dict over message passing**: `active_markets` is mutated by `buffer_maintainer` and read by `alert_engine`, `db_writer`, and `backstop`. `live_state`'s singletons follow the same pattern for tennis score/model state. This works because Python asyncio is single-threaded and coroutines yield cooperatively — no locking needed.
- **Two Redis consumer groups on `ticks`**: `buffer_maintainer` and `alert_engine` each get every message independently. The alert engine checks `active_markets` to skip ticks for markets whose buffer isn't populated yet.
- **db_writer uses wall-clock polling, not the stream**: It snapshots only the *latest* tick per buffer every 5 seconds, not every tick — this is intentional to avoid write amplification.
- **`markets_history` is a module-level global**: The analytics service holds per-ticker history in-process. This state is lost on restart; volume/momentum will be 0 until the 60s window re-fills.
- **`contract_buffer.maxlen` is hardcoded at 600** regardless of the constructor argument — the `__init__` ignores its `maxlen` param and always uses 600.
- **`close_time` vs `open_time`**: see **Data Retention** above — this bit us in practice (matches showed as "upcoming" for two weeks after finishing) and is worth remembering before adding any new query that needs to know whether a match is "still relevant."
- **`fetch_market` vs the old `fetch_closed_market`**: Kalshi's regular `/markets/{ticker}` endpoint already returns `status`/`result` once a market settles; the `/historical/markets/{ticker}` endpoint 404s for these tickers and was removed.

## API Endpoints

- `GET /health/` — liveness check
- `GET /markets/?limit=N&cursor=...` — proxies Kalshi market list, upserts each market into `market_meta`, returns raw payload
- `GET /markets/search?q=` — title search, excludes stale unresolved markets (see **Data Retention**)
- `GET /markets/upcoming?limit=N` — landing page data: unresolved matches grouped by `event_ticker` into player pairs, with each player's latest traded price and the ticker-derived `match_date` (not `open_time` — see **Data Retention**)
- `GET /markets/{ticker}` — market metadata
- `GET /markets/{ticker}/snapshots?limit=N` — time-series analytics rows, including `model_price`
- `GET /markets/{ticker}/score` — live scoreboard + model price for a mapped market, reading straight from `live_state`; returns `{"mapped": false}` (200, not 404) when unlinked
- `GET /alerts/stream?market=` — SSE alert feed
