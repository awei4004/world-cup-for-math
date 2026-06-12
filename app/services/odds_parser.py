"""Odds parser — REAL Chinese sports lottery odds (竞彩) + fallback generation."""
import json
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from pathlib import Path

from app.models.odds import Odds
from app.models.prediction import Prediction


class OddsParser:
    """Real竞彩 odds, loaded from verified sporttery.cn data."""

    # Cache for real odds data
    _real_odds = None

    @classmethod
    def load_real_odds(cls) -> dict:
        """Load real竞彩赔率 from JSON file."""
        if cls._real_odds is None:
            path = Path(__file__).resolve().parent.parent.parent / "data" / "seed" / "odds_real.json"
            with open(path, "r", encoding="utf-8") as f:
                cls._real_odds = json.load(f)
        return cls._real_odds

    @classmethod
    def get_real_odds(cls, home_code: str, away_code: str) -> Optional[dict]:
        """Get real竞彩 odds for a match pair. Returns None if not found."""
        data = cls.load_real_odds()
        key = f"{home_code}-{away_code}"
        return data["matches"].get(key)

    @classmethod
    def generate_odds_from_prediction(cls, pred: Prediction) -> tuple:
        """Generate realistic odds from model prediction (fallback for unlisted matches)."""
        if not pred:
            return (2.50, 3.20, 2.80)

        p_home = max(pred.prob_home_win, 0.05)
        p_draw = max(pred.prob_draw, 0.05)
        p_away = max(pred.prob_away_win, 0.05)
        total = p_home + p_draw + p_away
        p_home, p_draw, p_away = p_home/total, p_draw/total, p_away/total

        # 竞彩 margin ~8%
        margin = 1.08
        odds_home = 1.0 / (p_home * margin)
        odds_draw = 1.0 / (p_draw * margin)
        odds_away = 1.0 / (p_away * margin)

        return (
            round(max(1.08, odds_home), 2),
            round(max(1.15, odds_draw), 2),
            round(max(1.08, odds_away), 2),
        )

    @staticmethod
    async def update_odds_for_match(db: AsyncSession, match_id: int) -> Optional[Odds]:
        """Set odds using REAL竞彩 data, fallback to model-generated."""
        from app.models.match import Match
        result = await db.execute(
            select(Match).where(Match.id == match_id)
        )
        match = result.scalar_one_or_none()
        if not match:
            return None

        # Try real竞彩 odds first
        result = await db.execute(
            select(Prediction).where(Prediction.match_id == match_id)
        )
        pred = result.scalar_one_or_none()

        # Query home/away team codes
        from app.models.team import Team
        home = await db.get(Team, match.home_team_id)
        away = await db.get(Team, match.away_team_id)

        real_odds = OddsParser.get_real_odds(home.fifa_code, away.fifa_code)
        if real_odds:
            win, draw, lose = real_odds["win"], real_odds["draw"], real_odds["lose"]
            source = "竞彩官方"
        elif pred:
            win, draw, lose = OddsParser.generate_odds_from_prediction(pred)
            source = "模型生成"
        else:
            win, draw, lose = (2.50, 3.20, 2.80)
            source = "默认"

        # Upsert odds
        result = await db.execute(
            select(Odds).where(Odds.match_id == match_id)
        )
        odds = result.scalar_one_or_none()

        if odds:
            odds.win_odds = win
            odds.draw_odds = draw
            odds.lose_odds = lose
            odds.source = source
            odds.updated_at = datetime.utcnow()
        else:
            odds = Odds(
                match_id=match_id, source=source,
                win_odds=win, draw_odds=draw, lose_odds=lose,
                updated_at=datetime.utcnow(),
            )
            db.add(odds)

        await db.flush()
        return odds

    @staticmethod
    def implied_probability(win: float, draw: float, lose: float) -> Dict[str, float]:
        """Remove overround, get fair implied probabilities."""
        total = 1/win + 1/draw + 1/lose
        return {
            "home": (1/win) / total,
            "draw": (1/draw) / total,
            "away": (1/lose) / total,
        }
