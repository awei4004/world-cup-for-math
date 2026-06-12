"""Prediction, BetRecommendation, and MatchResult models."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.models.database import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False, unique=True, index=True)
    model_version = Column(String(20), default="1.0")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Win/Draw/Loss probabilities
    prob_home_win = Column(Float, default=0.33)
    prob_draw = Column(Float, default=0.34)
    prob_away_win = Column(Float, default=0.33)

    # Expected goals
    expected_home_goals = Column(Float, default=1.2)
    expected_away_goals = Column(Float, default=1.0)

    # Score probability distribution (JSON: {"1-0": 0.12, "2-0": 0.08, ...})
    score_probs_json = Column(Text, default="{}")

    # Total goals probability distribution
    total_goals_probs_json = Column(Text, default="{}")

    # Model confidence (0-100)
    confidence_score = Column(Float, default=50.0)

    # Sub-model contributions for transparency
    elo_prob_home = Column(Float, nullable=True)
    elo_prob_draw = Column(Float, nullable=True)
    elo_prob_away = Column(Float, nullable=True)
    xgboost_prob_home = Column(Float, nullable=True)
    xgboost_prob_draw = Column(Float, nullable=True)
    xgboost_prob_away = Column(Float, nullable=True)

    match = relationship("Match", back_populates="prediction")

    def get_score_probs(self):
        return json.loads(self.score_probs_json) if self.score_probs_json else {}

    def get_total_goals_probs(self):
        return json.loads(self.total_goals_probs_json) if self.total_goals_probs_json else {}

    def to_dict(self):
        return {
            "match_id": self.match_id, "model_version": self.model_version,
            "prob_home_win": round(self.prob_home_win, 4),
            "prob_draw": round(self.prob_draw, 4),
            "prob_away_win": round(self.prob_away_win, 4),
            "expected_home_goals": round(self.expected_home_goals, 2),
            "expected_away_goals": round(self.expected_away_goals, 2),
            "confidence_score": round(self.confidence_score, 1),
        }


class BetRecommendation(Base):
    __tablename__ = "bet_recommendations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    strategy_name = Column(String(100), default="default")

    # JSON list of {match_id, bet_type, selection, odds, predicted_prob}
    matches_json = Column(Text, default="[]")

    bet_type = Column(String(20), default="单关")  # 单关/2串1/3串1/4串1
    total_odds = Column(Float, default=1.0)
    expected_value = Column(Float, default=0.0)
    kelly_fraction = Column(Float, default=0.0)
    suggested_stake = Column(Float, default=0.0)
    explanation = Column(Text, default="")

    # Track results
    is_won = Column(String(10), nullable=True)  # "won"/"lost"/"pending"

    def get_matches(self):
        return json.loads(self.matches_json)

    def to_dict(self):
        return {
            "id": self.id, "created_at": self.created_at.isoformat(),
            "strategy_name": self.strategy_name,
            "bet_type": self.bet_type, "total_odds": round(self.total_odds, 2),
            "expected_value": round(self.expected_value, 4),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "suggested_stake": round(self.suggested_stake, 2),
            "is_won": self.is_won,
        }


class MatchResult(Base):
    __tablename__ = "match_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    actual_home_score = Column(Integer, nullable=False)
    actual_away_score = Column(Integer, nullable=False)
    prediction_accuracy_score = Column(Float, default=0.0)  # How accurate was our prediction
    recorded_at = Column(DateTime, default=datetime.utcnow)


class BetLedger(Base):
    """Tracks actual bets placed and their outcomes for bankroll management."""
    __tablename__ = "bet_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recommendation_id = Column(Integer, ForeignKey("bet_recommendations.id"), nullable=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    bet_type = Column(String(20), default="单关")  # 单关/2串1/3串1/4串1
    selection = Column(String(20), default="")     # 胜/平/负
    stake = Column(Float, default=0.0)             # Amount wagered
    odds = Column(Float, default=1.0)              # Odds at time of bet
    result = Column(String(10), default="pending") # pending/won/lost/void
    profit = Column(Float, default=0.0)            # Profit (negative = loss)
    created_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)

    recommendation = relationship("BetRecommendation")
