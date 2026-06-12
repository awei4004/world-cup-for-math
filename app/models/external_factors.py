"""External factors model — per-match environmental and situational factors."""
from sqlalchemy import Column, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship

from app.models.database import Base


class ExternalFactors(Base):
    __tablename__ = "external_factors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False, unique=True, index=True)

    # Travel fatigue (0-100, higher = more tired)
    home_travel_fatigue = Column(Float, default=0.0)
    away_travel_fatigue = Column(Float, default=0.0)

    # Weather impact (-10 to +10, positive = favorable)
    weather_impact_home = Column(Float, default=0.0)
    weather_impact_away = Column(Float, default=0.0)

    # Referee bias (-10 to +10, positive = favors home)
    referee_bias_score = Column(Float, default=0.0)

    # Altitude advantage (0-100, who benefits from altitude)
    altitude_advantage = Column(Float, default=0.0)

    # Crowd support (0-100)
    home_crowd_support = Column(Float, default=50.0)

    # Media pressure (0-100)
    media_pressure_score = Column(Float, default=50.0)

    # Rest advantage (positive = home team rested more)
    rest_day_advantage = Column(Float, default=0.0)

    # Motivation (0-100, 0=already qualified, 100=must-win)
    motivation_factor = Column(Float, default=80.0)

    # Market sentiment (-1 to +1, positive = market favors home)
    betting_market_sentiment = Column(Float, default=0.0)

    # --- Additional off-field factors ---

    # Manager stability (-5 to 0, 0=stable, negative=instability)
    manager_change_impact = Column(Float, default=0.0)

    # Squad harmony (0-100, 100=perfect harmony)
    squad_harmony_score = Column(Float, default=80.0)

    # Historical head-to-head advantage (-1 to +1, positive = home historically dominant)
    h2h_advantage = Column(Float, default=0.0)

    # Days since last match for each team
    days_since_last_home = Column(Float, default=5.0)
    days_since_last_away = Column(Float, default=5.0)

    match = relationship("Match", back_populates="external_factors")

    def to_dict(self):
        return {
            "match_id": self.match_id,
            "home_travel_fatigue": self.home_travel_fatigue,
            "away_travel_fatigue": self.away_travel_fatigue,
            "weather_impact_home": self.weather_impact_home,
            "weather_impact_away": self.weather_impact_away,
            "referee_bias_score": self.referee_bias_score,
            "altitude_advantage": self.altitude_advantage,
            "home_crowd_support": self.home_crowd_support,
            "rest_day_advantage": self.rest_day_advantage,
            "motivation_factor": self.motivation_factor,
        }
