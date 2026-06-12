"""Betting recommendation route."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path

from app.models.database import get_db
from app.models.prediction import BetRecommendation

router = APIRouter(prefix="/betting", tags=["Betting"])
templates_dir = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))


@router.get("/", response_class=HTMLResponse)
async def betting_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Betting recommendations page."""
    from app.services.bet_optimizer import BetOptimizer
    from app.models.prediction import BetLedger

    result = await db.execute(
        select(BetRecommendation)
        .order_by(BetRecommendation.expected_value.desc())
        .limit(20)
    )
    recommendations = result.scalars().all()

    # Get bankroll summary
    optimizer = BetOptimizer(db)
    summary = await optimizer.get_bankroll_summary()

    # Get recent ledger entries
    result = await db.execute(
        select(BetLedger).order_by(BetLedger.created_at.desc()).limit(20)
    )
    ledger = result.scalars().all()

    template = jinja_env.get_template("betting.html")
    html = template.render(
        request=request,
        recommendations=recommendations,
        ledger=ledger,
        bankroll=summary["bankroll"],
        total_profit=summary["total_profit"],
        today_staked=summary["today_staked"],
        today_remaining=summary["today_remaining"],
        title="投注推荐 - 价值投注 & 过关组合",
    )
    return HTMLResponse(html)


@router.get("/api/recommendations")
async def get_recommendations(db: AsyncSession = Depends(get_db)):
    """API: Get current betting recommendations."""
    from app.services.bet_optimizer import BetOptimizer
    optimizer = BetOptimizer(db)
    return await optimizer.get_recommendations()


@router.post("/api/optimize")
async def run_optimization(db: AsyncSession = Depends(get_db)):
    """API: Run the betting optimizer."""
    from app.services.bet_optimizer import BetOptimizer
    optimizer = BetOptimizer(db)
    return await optimizer.optimize()


@router.post("/api/place-bet/{rec_id}")
async def place_bet(rec_id: int, db: AsyncSession = Depends(get_db)):
    """API: Place a bet from a recommendation."""
    from app.services.bet_optimizer import BetOptimizer
    optimizer = BetOptimizer(db)
    return await optimizer.place_bet(rec_id)


@router.post("/api/cancel-bet/{bet_id}")
async def cancel_bet_entry(bet_id: int, db: AsyncSession = Depends(get_db)):
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


@router.get("/api/bankroll")
async def get_bankroll(db: AsyncSession = Depends(get_db)):
    """API: Get current bankroll summary."""
    from app.services.bet_optimizer import BetOptimizer
    optimizer = BetOptimizer(db)
    return await optimizer.get_bankroll_summary()


