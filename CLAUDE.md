# BetMuse

Predictive analytics platform for peer-to-peer prediction markets (Kalshi). Ingests live market data via WebSocket, computes real-time analytics, fires signal alerts, and persists snapshots to PostgreSQL.

## Architecture Overview

The system is a single async Python process that runs several cooperative coroutines. All coordination between them uses a shared in-memory dict (`active_markets: dict[str, contract_buffer]`) and a Redis Stream (`ticks`).

```
Kalshi WS  ──►  ws_loop  ──►  Redis Stream "ticks"
                                    │
                   ┌────────────────┼──────────────────┐
                   ▼                ▼                   ▼
           buffer_maintainer   alert_engine         db_writer
           (group: buffer_maintainer) (group: alert_engine)  (timer-based)
                   │                │
           active_markets       active_markets
                   │
               backstop (timer, resolves closed markets)
```

**Entry point:** `app/runner.py::run_websocket_client` — creates Redis consumer groups and gathers all coroutines.

**FastAPI app:** `app/main.py` — starts `run_websocket_client` as a background task when `KALSHI_WS_RUN=1`.

## Workers

| Worker | File | How triggered | Purpose |
|---|---|---|---|
| `ws_loop` | `app/websockets/client.py` | Continuous WS stream | Connects to Kalshi, deserializes ticker_v2 messages, computes analytics, writes `Tick` objects to Redis stream `ticks` |
| `buffer_maintainer` | `app/workers/buffer_maintainer.py` | Redis consumer group `buffer_maintainer` | Creates/updates per-market `contract_buffer` in `active_markets`; on first-seen market, fetches metadata from Kalshi REST and upserts `market_meta` via `set_market` |
| `alert_engine` | `app/workers/alert_engine.py` | Redis consumer group `alert_engine` | Reads ticks, runs detectors against the in-memory buffer tail, writes fired signals to Redis stream `alerts` (maxlen 10000); 30s per-market cooldown |
| `db_writer` | `app/workers/db_writer.py` | `asyncio.sleep(10)` interval | Snapshots the latest tick from each dirty buffer to `market_snapshots` via `bulk_insert_ticks` |
| `backstop` | `app/workers/backstop.py` | `asyncio.sleep(1800)` interval | Polls Kalshi historical API for unresolved markets past close_time, resolves them in DB, evicts resolved/stale buffers from `active_markets` |

## Core Data Types

**`Tick`** (`app/core/contract_buffer.py`) — Pydantic model, the canonical per-tick data unit. Fields: `market`, `price`, `bid`, `ask`, `spread`, `volume_1s/10s/60s`, `imbalance`, `momentum`, `last_trade_ts`, and optional `no_bid/ask`, `liquidity`, `open_interest`, `dollar_volume/open_interest`, `bid_size`, `ask_size`, `last_trade_size`.

**`contract_buffer`** (`app/core/contract_buffer.py`) — Rolling deque (maxlen=600 ticks) per market. Tracks `last_seen` (monotonic) and `last_written` to drive the db_writer dirty check. `tail(n)` returns the last n ticks as a list.

## Detectors (`app/services/detectors.py`)

All detectors take a `window: list[Tick]` (typically the last 25 ticks). Each computes `recent - baseline` where baseline = mean of first 10 items and recent = mean of last 5 items.

| Detector | Signal | Threshold |
|---|---|---|
| `microprice_delta` | Size-weighted mid (bid×ask_size + ask×bid_size) / (bid_size+ask_size) shift | ±0.02 |
| `volume_spike` | `volume_10s` delta | ±100 |
| `imbalance_shift` | `(bid-ask)/(bid+ask)` delta | ±0.1 |
| `spread_compression` | `spread` delta | ±0.01 |
| `liquidity_drain` | `liquidity` delta | ≤ -5.0 |

Alert payloads go to Redis stream `alerts` with fields: `market`, `type`, `direction`, `value`, `ts`.

## Analytics Pipeline (`app/services/market_analytics.py`)

`compute_market_analytics(ticker, msg)` transforms a raw Kalshi `ticker_v2` WebSocket message into the analytics dict consumed by `Tick`. Maintains a per-process `markets_history` deque (in-module global) for sliding-window volume and momentum computation. History is trimmed to 60 seconds. Prices are in dollars (Kalshi sends `price_dollars`, `yes_bid_dollars`, `yes_ask_dollars`).

## Database Schema

Managed by Alembic. Two tables:

**`market_meta`** — one row per market ticker. Fields: `ticker` (unique), `event_ticker`, `series_ticker`, `title`, `open_time`, `close_time`, `result` (nullable bool). Indexed on `ticker`, `event_ticker`, `series_ticker`.

**`market_snapshots`** — time-series snapshots. Fields: `ticker`, `snapshot_time`, `last_price`, `yes_bid/ask`, `no_bid/ask`, `open_interest`, `liquidity`, `bid_size`, `ask_size`, `last_trade_size`, `last_trade_ts`. Compound index on `(ticker, snapshot_time)`.

Run migrations: `alembic upgrade head`

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

## Running Locally

```bash
# Infrastructure
docker-compose up postgres redis

# Backend
uvicorn app.main:app --reload
# With WS enabled:
KALSHI_WS_RUN=1 uvicorn app.main:app --reload

# Frontend (Vite + React 19)
cd frontend && npm run dev   # http://localhost:5173
```

## Key Design Decisions

- **Shared dict over message passing**: `active_markets` is mutated by `buffer_maintainer` and read by `alert_engine`, `db_writer`, and `backstop`. This works because Python asyncio is single-threaded and coroutines yield cooperatively — no locking needed.
- **Two Redis consumer groups on `ticks`**: `buffer_maintainer` and `alert_engine` each get every message independently. The alert engine checks `active_markets` to skip ticks for markets whose buffer isn't populated yet.
- **db_writer uses wall-clock polling, not the stream**: It snapshots only the *latest* tick per buffer every 10 seconds, not every tick — this is intentional to avoid write amplification.
- **`markets_history` is a module-level global**: The analytics service holds per-ticker history in-process. This state is lost on restart; volume/momentum will be 0 until the 60s window re-fills.
- **`contract_buffer.maxlen` is hardcoded at 600** regardless of the constructor argument — the `__init__` ignores its `maxlen` param and always uses 600.

## API Endpoints

- `GET /health/` — liveness check
- `GET /markets/?limit=N&cursor=...` — proxies Kalshi market list, upserts each market into `market_meta`, returns raw payload
