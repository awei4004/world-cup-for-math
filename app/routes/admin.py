"""Admin panel routes."""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path
from datetime import datetime

from app.models.database import get_db
from app.models.match import Match
from app.models.odds import Odds
from app.models.team import Team

router = APIRouter(prefix="/admin", tags=["Admin"])
templates_dir = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))


@router.get("/", response_class=HTMLResponse)
async def admin_panel(request: Request, db: AsyncSession = Depends(get_db)):
    """Admin panel main page."""
    result = await db.execute(
        select(Match).where(Match.status.in_(["scheduled", "live"]))
        .order_by(Match.match_date).limit(50)
    )
    matches = result.scalars().all()

    result = await db.execute(select(Team).order_by(Team.name_cn))
    teams = result.scalars().all()

    template = jinja_env.get_template("admin.html")
    html = template.render(
        request=request,
        matches=matches,
        teams=teams,
        title="管理后台",
    )
    return HTMLResponse(html)


@router.post("/match/{match_id}/result")
async def update_match_result(
    match_id: int,
    home_score: int = Form(...),
    away_score: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Update match result."""
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        return {"error": "Match not found"}

    match.home_score = home_score
    match.away_score = away_score
    match.status = "finished"
    await db.commit()

    return RedirectResponse(url="/admin?updated=1", status_code=303)


@router.post("/match/{match_id}/odds")
async def update_odds(
    match_id: int,
    win_odds: float = Form(None),
    draw_odds: float = Form(None),
    lose_odds: float = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Update odds for a match."""
    result = await db.execute(select(Odds).where(Odds.match_id == match_id))
    odds = result.scalar_one_or_none()

    if not odds:
        odds = Odds(match_id=match_id, updated_at=datetime.utcnow())
        db.add(odds)

    if win_odds is not None:
        odds.win_odds = win_odds
    if draw_odds is not None:
        odds.draw_odds = draw_odds
    if lose_odds is not None:
        odds.lose_odds = lose_odds
    odds.updated_at = datetime.utcnow()

    await db.commit()
    return RedirectResponse(url="/admin?updated=1", status_code=303)


# Separate router for API endpoints (without /admin prefix)
api_router = APIRouter(prefix="", tags=["Odds"])


@api_router.post("/api/odds/update")
async def update_odds_from_json(request: Request, db: AsyncSession = Depends(get_db)):
    """Update odds from structured JSON data (竞彩官方赔率)."""
    from app.services.odds_scraper import OddsUpdater
    data = await request.json()
    count = await OddsUpdater.update_odds_from_json(db, data)
    return {"status": "ok", "updated": count}
