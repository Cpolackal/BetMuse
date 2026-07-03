import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.health.route import router as health_router
from app.routes.markets.route import router as market_router
from app.routes.alerts.route import router as alerts_router

# from app.routes.calibration import router as calibration_router
# from app.websockets.market_ws import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start Kalshi WebSocket client in background when enabled
    ws_task = None
    if os.getenv("KALSHI_WS_RUN", "").strip().lower() in ("1", "true", "yes"):
        from app.runner import run_websocket_client
        ws_task = asyncio.create_task(run_websocket_client())
    yield
    if ws_task and not ws_task.done():
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="BetMuse", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/health", tags=["health"])
    app.include_router(market_router, prefix="/markets", tags=["markets"])
    app.include_router(alerts_router, prefix="/alerts", tags=["alerts"])
    # app.include_router(calibration_router, prefix="/calibration")
    # app.include_router(ws_router, prefix="/ws")

    return app


app = create_app()