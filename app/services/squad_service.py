"""Player squad service — market value and injury impact calculations."""
import math
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.team import Team, TeamSquad


class SquadService:
    """Calculate team strength adjustments based on squad quality and injuries."""

    VALUE_PER_GOAL = 0.15  # Every 100M EUR market value difference ≈ +0.15 xG

    SEVERITY_WEIGHTS = {
        "轻伤": 0.5,
        "中度": 0.75,
        "重伤": 1.0,
        "赛季报销": 1.5,
        "": 0.75,  # default
    }

    @staticmethod
    async def get_team_squad_summary(db: AsyncSession, team_id: int) -> dict:
        """Get aggregated squad statistics for a team."""
        team = await db.get(Team, team_id)
        if not team:
            return {}

        result = await db.execute(
            select(TeamSquad).where(TeamSquad.team_id == team_id)
        )
        players = result.scalars().all()

        if not players:
            # Fallback: use team-level data
            return {
                "total_value": team.total_market_value or 300_000_000,
                "avg_starter_value": (team.total_market_value or 300_000_000) / 11,
                "squad_depth_score": 50.0,
                "injury_impact": team.injury_impact_score or 0.0,
                "key_players_missing": 0,
            }

        starters = [p for p in players if p.is_starter]
        injured = [p for p in players if p.is_injured]

        # Calculate starter average value
        if starters:
            starter_value = sum(p.market_value for p in starters if p.market_value) / max(len(starters), 1)
        else:
            starter_value = sum(p.market_value for p in players if p.market_value) / max(len(players), 1)

        # Squad depth: ratio of bench value to starter value
        bench = [p for p in players if not p.is_starter]
        if bench and starters:
            bench_avg = sum(p.market_value for p in bench if p.market_value) / max(len(bench), 1)
            depth_score = min(bench_avg / max(starter_value, 1) * 100, 100)
        else:
            depth_score = 50.0

        # Injury impact
        injury_impact = SquadService._calculate_injury_impact(injured)

        # Count key missing players (importance > 70)
        key_missing = sum(1 for p in injured if p.importance_score > 70)

        return {
            "total_value": team.total_market_value or 300_000_000,
            "avg_starter_value": starter_value,
            "squad_depth_score": round(depth_score, 1),
            "injury_impact": round(injury_impact, 1),
            "key_players_missing": key_missing,
            "starter_count": len(starters),
            "injured_count": len(injured),
        }

    @staticmethod
    def _calculate_injury_impact(injured_players: list) -> float:
        """Calculate aggregated injury impact score (0-100)."""
        score = 0.0
        for p in injured_players:
            base = p.importance_score * 0.8 if p.is_starter else p.importance_score * 0.3
            severity = SquadService.SEVERITY_WEIGHTS.get(
                p.injury_detail, SquadService.SEVERITY_WEIGHTS[""]
            )
            score += base * severity
        return min(score, 100.0)

    @staticmethod
    def value_to_xg_modifier(home_value: float, away_value: float) -> float:
        """Convert market value difference to xG modifier."""
        if away_value <= 0:
            return 1.0
        ratio = home_value / away_value
        # Log relationship: 2x value ≈ +0.10 xG
        return 1.0 + 0.10 * math.log2(max(ratio, 0.1))

    @staticmethod
    def injury_to_xg_modifier(injury_score: float) -> float:
        """Convert injury impact to xG reduction factor."""
        # injury_score 0 → factor 1.0 (no impact)
        # injury_score 50 → factor 0.85
        # injury_score 100 → factor 0.70
        return 1.0 - (injury_score / 100) * 0.30
