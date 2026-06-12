"""Odds model — Chinese sports lottery odds."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.models.database import Base


class Odds(Base):
    __tablename__ = "odds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False, unique=True, index=True)
    source = Column(String(50), default="竞彩官方")
    updated_at = Column(DateTime, default=datetime.utcnow)

    # 胜平负 (Win/Draw/Loss)
    win_odds = Column(Float, nullable=True)
    draw_odds = Column(Float, nullable=True)
    lose_odds = Column(Float, nullable=True)

    # 让球胜平负 (Handicap)
    handicap = Column(Float, nullable=True)          # e.g. -1, +0.5
    handicap_win = Column(Float, nullable=True)
    handicap_draw = Column(Float, nullable=True)
    handicap_lose = Column(Float, nullable=True)

    # 总进球数大小
    over_2_5 = Column(Float, nullable=True)
    under_2_5 = Column(Float, nullable=True)

    # 总进球数精确
    goal_0 = Column(Float, default=0.0)
    goal_1 = Column(Float, default=0.0)
    goal_2 = Column(Float, default=0.0)
    goal_3 = Column(Float, default=0.0)
    goal_4 = Column(Float, default=0.0)
    goal_5 = Column(Float, default=0.0)
    goal_6 = Column(Float, default=0.0)
    goal_7plus = Column(Float, default=0.0)

    # 比分赔率 (stored as JSON string)
    score_odds_json = Column(Text, default="{}")

    match = relationship("Match", back_populates="odds")

    def get_score_odds(self):
        import json
        return json.loads(self.score_odds_json)

    def implied_probability_1x2(self):
        """Calculate market-implied probabilities from 1X2 odds."""
        if not all([self.win_odds, self.draw_odds, self.lose_odds]):
            return None
        # Remove overround
        total = 1/self.win_odds + 1/self.draw_odds + 1/self.lose_odds
        return {
            "home": (1/self.win_odds) / total,
            "draw": (1/self.draw_odds) / total,
            "away": (1/self.lose_odds) / total,
        }

    def to_dict(self):
        return {
            "match_id": self.match_id, "source": self.source,
            "win_odds": self.win_odds, "draw_odds": self.draw_odds,
            "lose_odds": self.lose_odds,
            "handicap": self.handicap,
            "handicap_win": self.handicap_win,
            "handicap_draw": self.handicap_draw,
            "handicap_lose": self.handicap_lose,
            "over_2_5": self.over_2_5, "under_2_5": self.under_2_5,
        }
