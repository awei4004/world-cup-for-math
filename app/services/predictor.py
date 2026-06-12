"""Main prediction engine — combines Elo, Poisson, and ML models."""
import json
import math
from typing import Optional, Tuple
from scipy.stats import poisson
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.database import get_db
from app.models.match import Match
from app.models.team import Team
from app.models.prediction import Prediction
from app.services.elo import EloService
from app.services.squad_service import SquadService
from app.services.external_factors import ExternalFactorsService
from app.services.feature_engine import FeatureEngine


class PredictionEngine:
    """Generate match predictions using ensemble of models."""

    MAX_GOALS = 8  # Max goals to consider per team

    def __init__(self, db: AsyncSession):
        self.db = db
        self.elo_service = EloService()
        self.feature_engine = FeatureEngine()

    async def predict_match(self, match_id: int) -> Prediction:
        """Generate full prediction for a match."""
        result = await self.db.execute(
            select(Match).options(
                selectinload(Match.home_team),
                selectinload(Match.away_team),
                selectinload(Match.external_factors),
            ).where(Match.id == match_id)
        )
        match = result.scalar_one_or_none()
        if not match:
            raise ValueError(f"Match {match_id} not found")

        home = match.home_team
        away = match.away_team

        # Ensure external factors are evaluated
        factors = match.external_factors
        if not factors:
            factors = await ExternalFactorsService.evaluate_match(self.db, match_id)

        # Get squad data
        home_squad = await SquadService.get_team_squad_summary(self.db, home.id)
        away_squad = await SquadService.get_team_squad_summary(self.db, away.id)

        # Get home advantage bonus
        home_bonus = EloService.get_home_bonus(
            home.is_host, home.host_country, match.city, home.confederation
        )

        # === ENSEMBLE PREDICTION ===

        # 1. Elo-based prediction
        elo_home, elo_draw, elo_away = EloService.win_probability(
            home.elo_rating, away.elo_rating, home_bonus
        )

        # 2. Adjusted expected goals (xG)
        home_xg = EloService.expected_goals(home.elo_rating, away.elo_rating, home_bonus)
        away_xg = EloService.expected_goals(away.elo_rating, home.elo_rating, 0)

        # Apply player factor adjustments
        value_mod = SquadService.value_to_xg_modifier(
            home_squad.get("total_value", 300_000_000),
            away_squad.get("total_value", 300_000_000),
        )
        home_injury_mod = SquadService.injury_to_xg_modifier(
            home_squad.get("injury_impact", 0.0)
        )
        away_injury_mod = SquadService.injury_to_xg_modifier(
            away_squad.get("injury_impact", 0.0)
        )

        home_xg *= value_mod * home_injury_mod
        away_xg *= (1.0 / value_mod) * away_injury_mod

        # Apply external factor adjustments
        if factors:
            # Home crowd and weather advantage
            crowd_factor = 1.0 + 0.03 * (factors.home_crowd_support - 50) / 50
            home_xg *= crowd_factor

            # Motivation affects both teams' attack
            home_xg *= 0.9 + 0.002 * factors.motivation_factor
            away_xg *= 0.9 + 0.002 * factors.motivation_factor

            # Altitude reduces away team output
            if factors.altitude_advantage > 20:
                away_xg *= 0.85

        # Floor
        home_xg = max(0.15, home_xg)
        away_xg = max(0.1, away_xg)

        # 3. Score probability matrix (Poisson + Dixon-Coles)
        score_probs = self._score_probability_matrix(home_xg, away_xg)

        # 4. Win/Draw/Loss from score matrix
        sim_home, sim_draw, sim_away = self._probabilities_from_scores(score_probs)

        # 5. Total goals distribution
        total_goals_probs = self._total_goals_distribution(score_probs)

        # 6. Ensemble blending
        elo_weight = 0.40
        poisson_weight = 0.35
        # ML (XGBoost/GradientBoosting) weight — low initially
        ml_weight = 0.25
        ml_home, ml_draw, ml_away = sim_home, sim_draw, sim_away  # fallback

        try:
            features = self.feature_engine.build_features(
                home, away, match, factors, home_squad, away_squad
            )
            ml_home, ml_draw, ml_away = self._ml_predict(features)
        except Exception:
            pass  # Use Poisson as ML fallback

        # Blend
        final_home = elo_weight * elo_home + poisson_weight * sim_home + ml_weight * ml_home
        final_draw = elo_weight * elo_draw + poisson_weight * sim_draw + ml_weight * ml_draw
        final_away = elo_weight * elo_away + poisson_weight * sim_away + ml_weight * ml_away

        # Normalize
        total = final_home + final_draw + final_away
        final_home /= total
        final_draw /= total
        final_away /= total

        # Confidence based on Elo gap
        elo_gap = abs(home.elo_rating - away.elo_rating)
        if elo_gap > 300:
            confidence = 85.0
        elif elo_gap > 150:
            confidence = 70.0
        elif elo_gap > 50:
            confidence = 55.0
        else:
            confidence = 40.0

        # Store prediction
        result = await self.db.execute(
            select(Prediction).where(Prediction.match_id == match_id)
        )
        pred = result.scalar_one_or_none()

        score_json = json.dumps(
            {f"{h}-{a}": round(p, 6) for (h, a), p in score_probs.items()},
            ensure_ascii=False
        )
        goals_json = json.dumps(
            {str(k): round(v, 4) for k, v in total_goals_probs.items()},
            ensure_ascii=False
        )

        if pred:
            pred.prob_home_win = round(final_home, 4)
            pred.prob_draw = round(final_draw, 4)
            pred.prob_away_win = round(final_away, 4)
            pred.expected_home_goals = round(home_xg, 2)
            pred.expected_away_goals = round(away_xg, 2)
            pred.score_probs_json = score_json
            pred.total_goals_probs_json = goals_json
            pred.confidence_score = round(confidence, 1)
            pred.elo_prob_home = round(elo_home, 4)
            pred.elo_prob_draw = round(elo_draw, 4)
            pred.elo_prob_away = round(elo_away, 4)
        else:
            pred = Prediction(
                match_id=match_id,
                model_version="1.0",
                prob_home_win=round(final_home, 4),
                prob_draw=round(final_draw, 4),
                prob_away_win=round(final_away, 4),
                expected_home_goals=round(home_xg, 2),
                expected_away_goals=round(away_xg, 2),
                score_probs_json=score_json,
                total_goals_probs_json=goals_json,
                confidence_score=round(confidence, 1),
                elo_prob_home=round(elo_home, 4),
                elo_prob_draw=round(elo_draw, 4),
                elo_prob_away=round(elo_away, 4),
            )
            self.db.add(pred)

        await self.db.commit()
        return pred

    def _score_probability_matrix(self, home_xg: float, away_xg: float) -> dict:
        """Generate score probability matrix with Dixon-Coles low-score correction."""
        rho = -0.13
        matrix = {}

        for h in range(self.MAX_GOALS + 1):
            for a in range(self.MAX_GOALS + 1):
                prob = poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg)

                # Dixon-Coles correction for low-scoring matches
                if h == 0 and a == 0:
                    prob *= (1 + rho * home_xg * away_xg)
                elif h == 0 and a == 1:
                    prob *= (1 - rho * away_xg)
                elif h == 1 and a == 0:
                    prob *= (1 - rho * home_xg)
                elif h == 1 and a == 1:
                    prob *= (1 + rho)

                matrix[(h, a)] = max(prob, 0.0)

        # Normalize
        total = sum(matrix.values())
        if total > 0:
            matrix = {k: v / total for k, v in matrix.items()}

        return matrix

    def _probabilities_from_scores(self, score_probs: dict) -> Tuple[float, float, float]:
        """Calculate 1X2 probabilities from score probability matrix."""
        home_win = sum(p for (h, a), p in score_probs.items() if h > a)
        draw = sum(p for (h, a), p in score_probs.items() if h == a)
        away_win = sum(p for (h, a), p in score_probs.items() if h < a)

        total = home_win + draw + away_win
        if total > 0:
            return home_win / total, draw / total, away_win / total
        return 0.33, 0.34, 0.33

    def _total_goals_distribution(self, score_probs: dict) -> dict:
        """Aggregate score probabilities into total goals distribution."""
        dist = {}
        for (h, a), p in score_probs.items():
            total = h + a
            dist[total] = dist.get(total, 0.0) + p

        # Cap at 7+
        capped = {}
        for k, v in sorted(dist.items()):
            if k >= 7:
                capped["7+"] = capped.get("7+", 0.0) + v
            else:
                capped[str(k)] = round(v, 4)
        return capped

    def _ml_predict(self, features: dict) -> Tuple[float, float, float]:
        """ML model prediction using GradientBoosting (scikit-learn)."""
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            import pickle
            from pathlib import Path

            model_path = Path(__file__).resolve().parent.parent.parent / "data" / "model.pkl"

            if model_path.exists():
                with open(model_path, "rb") as f:
                    model = pickle.load(f)

                X = FeatureEngine.to_array(features).reshape(1, -1)
                probs = model.predict_proba(X)[0]
                # Model outputs: [home_win, draw, away_win]
                return probs[0], probs[1], probs[2]
        except Exception:
            pass

        # Fallback: use Elo-based estimate with slight noise
        elo_home = features.get("elo_win_prob", 0.40)
        elo_draw = features.get("elo_draw_prob", 0.28)
        elo_away = 1.0 - elo_home - elo_draw
        return elo_home, elo_draw, max(0.05, elo_away)

    async def predict_todays_matches(self):
        """Generate predictions for all scheduled matches today."""
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        result = await self.db.execute(
            select(Match)
            .where(Match.match_date >= today_start, Match.match_date < today_end)
            .where(Match.status == "scheduled")
        )
        matches = result.scalars().all()

        predictions = []
        for match in matches:
            pred = await self.predict_match(match.id)
            predictions.append(pred)

        return predictions
