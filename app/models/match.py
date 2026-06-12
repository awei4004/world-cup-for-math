"""Match and Group models."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship

from app.models.database import Base


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(2), nullable=False, unique=True)  # A through L
    teams_json = Column(Text, default="[]")  # JSON list of team ids

    teams = relationship("Team", back_populates="group",
                         foreign_keys="Team.group_id")

    def get_team_ids(self):
        return json.loads(self.teams_json)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name,
            "team_ids": self.get_team_ids(),
        }


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_date = Column(DateTime, nullable=False, index=True)
    stage = Column(String(30), default="小组赛")  # 小组赛, 1/16决赛, 1/8决赛, 1/4决赛, 半决赛, 季军赛, 决赛
    matchday = Column(Integer, default=1)         # Matchday within group stage

    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    status = Column(String(20), default="scheduled")  # scheduled / live / finished

    # Venue info
    venue = Column(String(100), default="")
    city = Column(String(50), default="")
    stadium = Column(String(100), default="")

    # Weather & environment
    temperature = Column(Float, nullable=True)   # Celsius
    weather = Column(String(30), default="")     # sunny/rainy/cloudy
    humidity = Column(Float, nullable=True)      # percentage
    altitude = Column(Float, default=0.0)        # meters

    # Travel
    travel_distance_home = Column(Float, default=0.0)
    travel_distance_away = Column(Float, default=0.0)

    # Referee
    referee_name = Column(String(100), default="")
    referee_nationality = Column(String(50), default="")

    # Relationships
    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])
    odds = relationship("Odds", back_populates="match", uselist=False, lazy="joined")
    prediction = relationship("Prediction", back_populates="match", uselist=False, lazy="joined")
    external_factors = relationship("ExternalFactors", back_populates="match", uselist=False, lazy="joined")

    def to_dict(self):
        return {
            "id": self.id, "match_date": self.match_date.isoformat() if self.match_date else None,
            "stage": self.stage, "matchday": self.matchday,
            "home_team_id": self.home_team_id, "away_team_id": self.away_team_id,
            "home_score": self.home_score, "away_score": self.away_score,
            "status": self.status,
            "venue": self.venue, "city": self.city, "stadium": self.stadium,
            "temperature": self.temperature, "weather": self.weather,
            "referee_name": self.referee_name,
        }
