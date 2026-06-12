"""Prediction API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.models.database import get_db
from app.models.match import Match
from app.models.prediction import Prediction

router = APIRouter(prefix="/api/predictions", tags=["Predictions"])


class PredictionResponse(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    expected_home_goals: float
    expected_away_goals: float
    top_scores: list
    total_goals_distribution: dict


@router.get("/match/{match_id}")
async def get_prediction(match_id: int, db: AsyncSession = Depends(get_db)):
    """Get prediction for a specific match."""
    result = await db.execute(
        select(Match)
        .options(
            selectinload(Match.home_team),
            selectinload(Match.away_team),
            selectinload(Match.prediction),
        )
        .where(Match.id == match_id)
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    pred = match.prediction
    if not pred:
        # Return empty prediction structure
        return {
            "match_id": match_id,
            "home_team": match.home_team.name_cn,
            "away_team": match.away_team.name_cn,
            "status": "no_prediction",
            "message": "预测尚未生成，请稍后刷新",
        }

    score_probs = pred.get_score_probs()
    top_scores = sorted(score_probs.items(), key=lambda x: x[1], reverse=True)[:8]

    return {
        "match_id": match.id,
        "home_team": match.home_team.name_cn,
        "away_team": match.away_team.name_cn,
        "prob_home_win": round(pred.prob_home_win, 4),
        "prob_draw": round(pred.prob_draw, 4),
        "prob_away_win": round(pred.prob_away_win, 4),
        "expected_home_goals": round(pred.expected_home_goals, 2),
        "expected_away_goals": round(pred.expected_away_goals, 2),
        "confidence": round(pred.confidence_score, 1),
        "top_scores": [{"score": k, "prob": round(v, 4)} for k, v in top_scores],
        "total_goals_distribution": pred.get_total_goals_probs(),
    }


@router.post("/generate/{match_id}")
async def generate_prediction(match_id: int, db: AsyncSession = Depends(get_db)):
    """Trigger prediction generation for a match."""
    from app.services.predictor import PredictionEngine
    engine = PredictionEngine(db)
    await engine.predict_match(match_id)
    return {"status": "ok", "match_id": match_id, "message": "预测已生成"}
