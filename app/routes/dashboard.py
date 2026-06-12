"""Dashboard route — main page showing today's matches and predictions."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from pathlib import Path

from app.models.database import get_db
from app.models.match import Match
from app.models.team import Team

router = APIRouter(prefix="", tags=["Dashboard"])
templates_dir = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Main dashboard showing today's and upcoming matches."""
    # Use Beijing time (UTC+8) since database stores Beijing time
    now_bj = datetime.utcnow() + timedelta(hours=8)
    today_start = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Today's matches
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team),
                 selectinload(Match.prediction), selectinload(Match.odds))
        .where(and_(Match.match_date >= today_start, Match.match_date < today_end))
        .order_by(Match.match_date)
    )
    today_matches = result.scalars().all()

    # Upcoming matches (next 3 days)
    future_end = today_end + timedelta(days=3)
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .where(and_(Match.match_date >= today_end, Match.match_date < future_end))
        .order_by(Match.match_date)
        .limit(20)
    )
    upcoming_matches = result.scalars().all()

    # Live matches
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team),
                 selectinload(Match.prediction))
        .where(Match.status == "live")
        .order_by(Match.match_date)
    )
    live_matches = result.scalars().all()

    # Recent results (finished today)
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .where(and_(Match.status == "finished", Match.match_date >= today_start))
        .order_by(Match.match_date.desc())
        .limit(10)
    )
    finished_matches = result.scalars().all()

    template = jinja_env.get_template("dashboard.html")
    html = template.render(
        request=request,
        today_matches=today_matches,
        upcoming_matches=upcoming_matches,
        live_matches=live_matches,
        finished_matches=finished_matches,
        now=now_bj,
        title="2026世界杯预测 - 仪表盘",
    )
    return HTMLResponse(html)


@router.post("/api/predict-all")
async def predict_all_matches(db: AsyncSession = Depends(get_db)):
    """Generate predictions for all scheduled upcoming matches."""
    from app.services.predictor import PredictionEngine
    from app.services.external_factors import ExternalFactorsService
    from sqlalchemy import select as sel
    from datetime import datetime, timedelta

    engine = PredictionEngine(db)
    now_bj = datetime.utcnow() + timedelta(hours=8)

    result = await db.execute(
        sel(Match).where(Match.status == "scheduled").limit(30)
    )
    matches = result.scalars().all()

    count = 0
    for match in matches:
        try:
            await ExternalFactorsService.evaluate_match(db, match.id)
            await engine.predict_match(match.id)
            count += 1
        except Exception as e:
            print(f"Error predicting match {match.id}: {e}")

    return {"status": "ok", "predicted": count, "total": len(matches)}
