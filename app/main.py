"""FastAPI application entry point."""
# RELOAD_MARKER
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.models.database import init_db, get_db
from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    await init_db()
    # Start background scheduler
    import asyncio
    asyncio.create_task(scrape_loop())
    yield


async def scrape_loop():
    """Background task: periodically scrape live scores and daily odds."""
    import asyncio
    from datetime import datetime, timedelta
    from app.models.database import async_session_factory
    from app.services.scraper import DongqiudiScraper
    from app.services.odds_scraper import OddsUpdater

    await asyncio.sleep(30)  # Wait for server to fully start
    print("[Scheduler] Live score scraper started (every 120s)")
    print("[Scheduler] Odds updater started (once daily)")

    odds_checked_today = False

    while True:
        try:
            async with async_session_factory() as db:
                # Score updates every 2 minutes
                updates = await DongqiudiScraper.fetch_live_scores(db)
                if updates:
                    print(f"[Scheduler] {len(updates)} score updates found")

                # Odds update once per day
                now_bj = datetime.utcnow() + timedelta(hours=8)
                if now_bj.hour == 10 and not odds_checked_today:  # 10 AM Beijing
                    count = await OddsUpdater.fetch_from_sina(db)
                    if count > 0:
                        print(f"[Scheduler] {count} odds updated from news source")
                    odds_checked_today = True
                elif now_bj.hour != 10:
                    odds_checked_today = False

        except Exception as e:
            print(f"[Scheduler] Error: {e}")
        await asyncio.sleep(120)  # Every 2 minutes


app = FastAPI(
    title="2026世界杯预测 - 体彩投注优化",
    description="2026 FIFA World Cup prediction & Chinese sports lottery betting optimizer",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Import and register routes
from app.routes import dashboard, matches, predictions, betting, admin

app.include_router(dashboard.router, tags=["Dashboard"])
app.include_router(matches.router, tags=["Matches"])
app.include_router(predictions.router, tags=["Predictions"])
app.include_router(betting.router, tags=["Betting"])
app.include_router(admin.router, tags=["Admin"])
app.include_router(admin.api_router, tags=["Odds"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "tournament": "2026 FIFA World Cup", "start_date": "2026-06-11"}


@app.post("/api/refresh")
async def refresh_data(db: AsyncSession = Depends(get_db)):
    """Manually trigger data refresh from Dongqiudi."""
    from app.services.scraper import DongqiudiScraper
    updates = await DongqiudiScraper.fetch_live_scores(db)
    return {"status": "ok", "updates": len(updates) if updates else 0}


@app.post("/api/odds/update")
async def update_odds(request: Request, db: AsyncSession = Depends(get_db)):
    """Update odds from structured JSON data (竞彩官方赔率)."""
    from app.services.odds_scraper import OddsUpdater
    data = await request.json()
    count = await OddsUpdater.update_odds_from_json(db, data)
    return {"status": "ok", "updated": count}


@app.get("/api/bankroll")
async def get_bankroll(db: AsyncSession = Depends(get_db)):
    """Get current bankroll summary."""
    from app.services.bet_optimizer import BetOptimizer
    optimizer = BetOptimizer(db)
    return await optimizer.get_bankroll_summary()


@app.post("/api/place-bet/{rec_id}")
async def place_bet(rec_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Place or cancel a bet. Add ?cancel=1 to undo a pending bet."""
    from app.services.bet_optimizer import BetOptimizer
    from sqlalchemy import select
    from app.models.prediction import BetLedger

    # Check query string for cancel flag
    qp = request.query_params
    if qp.get("cancel") in ("1", "true", "yes"):
        result = await db.execute(select(BetLedger).where(BetLedger.id == rec_id))
        bet = result.scalar_one_or_none()
        if not bet:
            return {"error": "Bet not found"}
        if bet.result != "pending":
            return {"error": "Cannot cancel settled bet"}
        await db.delete(bet)
        await db.commit()
        return {"status": "ok", "cancelled": rec_id}

    optimizer = BetOptimizer(db)
    return await optimizer.place_bet(rec_id)


@app.post("/api/cancel-bet/{bet_id}")
async def cancel_bet(bet_id: int, db: AsyncSession = Depends(get_db)):
    """Cancel a pending bet."""
    from sqlalchemy import select
    from app.models.prediction import BetLedger
    result = await db.execute(select(BetLedger).where(BetLedger.id == bet_id))
    bet = result.scalar_one_or_none()
    if not bet:
        return {"error": "Bet not found"}
    if bet.result != "pending":
        return {"error": "Cannot cancel settled bet"}
    await db.delete(bet)
    await db.commit()
    return {"status": "ok", "cancelled": bet_id}

