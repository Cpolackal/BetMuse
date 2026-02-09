from fastapi import FastAPI
from app.routes.health import router as health_router
from app.routes.markets import router as market_router

# from app.routes.health import router as health_router
# from app.routes.markets import router as markets_router
# from app.routes.calibration import router as calibration_router
# from app.websocket.market_ws import router as ws_router

def create_app() -> FastAPI:
    app = FastAPI(title="BetMuse")

    # Register routes
    app.include_router(health_router, prefix = "/health", tags = ["health"])
    app.include_router(market_router, prefix = "/markets", tags = ["markets"])
    # app.include_router(markets_router, prefix="/markets")
    # app.include_router(calibration_router, prefix="/calibration")
    # app.include_router(ws_router, prefix="/ws")

    return app

app = create_app()