"""Feature engineering — 33-dimension feature vector for XGBoost / ML models."""
import math
import numpy as np
from typing import Dict, Optional

from app.models.team import Team
from app.models.match import Match
from app.models.external_factors import ExternalFactors


class FeatureEngine:
    """Build the 33-dimension feature vector for match prediction."""

    @staticmethod
    def build_features(
        home_team: Team,
        away_team: Team,
        match: Match,
        factors: Optional[ExternalFactors] = None,
        home_squad: Optional[dict] = None,
        away_squad: Optional[dict] = None,
    ) -> Dict[str, float]:
        """
        Build the full 33-dimension feature set.

        Returns a dict of feature_name -> value for model input.
        """
        f = {}

        # === Basic strength (6 dims) ===
        f["elo_diff"] = home_team.elo_rating - away_team.elo_rating
        f["fifa_rank_diff"] = (away_team.fifa_ranking or 50) - (home_team.fifa_ranking or 50)
        f["elo_win_prob"] = FeatureEngine._elo_win_prob(home_team.elo_rating, away_team.elo_rating)
        f["elo_draw_prob"] = FeatureEngine._elo_draw_prob(home_team.elo_rating, away_team.elo_rating)
        f["recent_form_diff"] = (home_team.recent_form_score or 0.5) - (away_team.recent_form_score or 0.5)
        f["goal_diff_10"] = (home_team.recent_goals_scored or 1.5) - (away_team.recent_goals_conceded or 1.5)

        # === Player factors (7 dims) ===
        home_val = home_squad.get("total_value", 300_000_000) if home_squad else (home_team.total_market_value or 300_000_000)
        away_val = away_squad.get("total_value", 300_000_000) if away_squad else (away_team.total_market_value or 300_000_000)
        f["market_value_ratio"] = math.log(max(home_val / max(away_val, 1), 0.01))

        home_avg = home_squad.get("avg_starter_value", home_val / 11) if home_squad else home_val / 11
        away_avg = away_squad.get("avg_starter_value", away_val / 11) if away_squad else away_val / 11
        f["avg_starter_value_diff"] = home_avg - away_avg

        home_depth = home_squad.get("squad_depth_score", 50.0) if home_squad else 50.0
        away_depth = away_squad.get("squad_depth_score", 50.0) if away_squad else 50.0
        f["squad_depth_score_diff"] = home_depth - away_depth

        home_injury = home_squad.get("injury_impact", 0.0) if home_squad else (home_team.injury_impact_score or 0.0)
        away_injury = away_squad.get("injury_impact", 0.0) if away_squad else (away_team.injury_impact_score or 0.0)
        f["injury_impact_diff"] = away_injury - home_injury  # inverted: higher = better for home

        f["key_player_missing_home"] = float(home_squad.get("key_players_missing", 0) if home_squad else 0)
        f["key_player_missing_away"] = float(away_squad.get("key_players_missing", 0) if away_squad else 0)
        f["squad_age_diff"] = (home_team.avg_age or 26) - (away_team.avg_age or 26)

        # === Home advantage (8 dims) ===
        f["is_host_home"] = 1.0 if home_team.is_host else 0.0
        f["is_host_away"] = 1.0 if away_team.is_host else 0.0
        f["home_advantage_bonus"] = home_team.home_advantage_bonus or 0.0
        f["crowd_support_score"] = factors.home_crowd_support if factors else 50.0
        f["travel_fatigue_diff"] = (factors.away_travel_fatigue if factors else 30.0) - (factors.home_travel_fatigue if factors else 10.0)
        f["rest_day_advantage"] = factors.rest_day_advantage if factors else 0.0
        f["climate_adaptation"] = FeatureEngine._climate_adaptation(home_team.confederation, match.city or "")
        f["confederation_home_advantage"] = 1.0 if home_team.confederation == "CONCACAF" else 0.0

        # === External factors (8 dims) ===
        f["weather_impact_net"] = (factors.weather_impact_home if factors else 0.0) - (factors.weather_impact_away if factors else 0.0)
        f["altitude_effect"] = factors.altitude_advantage if factors else 0.0
        f["motivation_diff"] = (factors.motivation_factor if factors else 80.0) - 80.0  # baseline
        f["media_pressure_diff"] = 0.0  # default, can be updated manually
        f["market_sentiment"] = factors.betting_market_sentiment if factors else 0.0
        f["odds_movement"] = 0.0  # will be filled when odds data is available
        f["manager_stability"] = factors.manager_change_impact if factors else 0.0
        f["match_stage_importance"] = FeatureEngine._stage_weight(match.stage)

        # === Interaction features (4 dims) ===
        f["elo_x_home"] = f["elo_diff"] * f["is_host_home"]
        f["injury_x_stage"] = f["injury_impact_diff"] * f["match_stage_importance"]
        f["value_x_form"] = f["market_value_ratio"] * f["recent_form_diff"]
        f["fatigue_x_rest"] = f["travel_fatigue_diff"] * abs(f["rest_day_advantage"])

        return f

    @staticmethod
    def to_array(features: Dict[str, float]) -> np.ndarray:
        """Convert feature dict to numpy array in consistent order."""
        keys = sorted(features.keys())
        return np.array([features[k] for k in keys], dtype=np.float64)

    @staticmethod
    def _elo_win_prob(elo_home: float, elo_away: float) -> float:
        diff = elo_home + 100 - elo_away
        return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

    @staticmethod
    def _elo_draw_prob(elo_home: float, elo_away: float) -> float:
        diff = (elo_home + 100) - elo_away
        return 0.28 * math.exp(-(diff ** 2) / (2 * 200 ** 2))

    @staticmethod
    def _stage_weight(stage: str) -> float:
        weights = {
            "小组赛": 1.0, "1/16决赛": 1.5, "1/8决赛": 2.0,
            "1/4决赛": 2.5, "半决赛": 3.0, "季军赛": 1.5, "决赛": 3.5,
        }
        return weights.get(stage, 1.0)

    @staticmethod
    def _climate_adaptation(confederation: str, city: str) -> float:
        """Score how adapted a team is to the venue climate (0-100)."""
        hot_cities = {"Miami", "Houston", "Dallas", "Monterrey", "Atlanta"}
        cool_cities = {"Vancouver", "San Francisco", "Seattle", "Toronto", "Boston"}

        if confederation in ("CONCACAF", "AFC", "CAF"):
            base = 60.0
        elif confederation == "CONMEBOL":
            base = 50.0
        else:
            base = 40.0  # UEFA

        if city in hot_cities:
            if confederation in ("CONCACAF", "CAF"):
                base += 20
            elif confederation == "UEFA":
                base -= 10
        elif city in cool_cities:
            if confederation == "UEFA":
                base += 20

        return max(0, min(100, base))
