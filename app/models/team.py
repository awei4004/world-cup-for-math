"""Team and Squad models."""
import json
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.models.database import Base


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_cn = Column(String(50), nullable=False, unique=True)
    name_en = Column(String(100), nullable=False)
    fifa_code = Column(String(3), nullable=False, unique=True)  # 3-letter code
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    fifa_ranking = Column(Integer, default=0)
    elo_rating = Column(Float, default=1500.0)
    elo_rating_initial = Column(Float, default=1500.0)
    is_host = Column(Boolean, default=False)
    host_country = Column(String(50), default="")  # USA/CAN/MEX or empty
    confederation = Column(String(10), default="")  # UEFA/CONMEBOL/CONCACAF/AFC/CAF/OFC
    flag_url = Column(String(200), default="")

    # New fields for player-based factors
    total_market_value = Column(Float, default=0.0)   # Total squad value in EUR
    avg_age = Column(Float, default=26.0)
    squad_size = Column(Integer, default=26)
    injury_impact_score = Column(Float, default=0.0)  # 0-100, higher = more injured
    home_advantage_bonus = Column(Float, default=0.0)  # Host bonus for venue match

    # Recent form
    recent_form_score = Column(Float, default=0.5)     # 0-1, recent win rate
    recent_goals_scored = Column(Float, default=1.5)   # Avg goals scored last 10
    recent_goals_conceded = Column(Float, default=1.5) # Avg goals conceded last 10

    # Relationships
    squad = relationship("TeamSquad", back_populates="team", lazy="dynamic")
    group = relationship("Group", back_populates="teams", foreign_keys=[group_id])

    def to_dict(self):
        return {
            "id": self.id, "name_cn": self.name_cn, "name_en": self.name_en,
            "fifa_code": self.fifa_code, "fifa_ranking": self.fifa_ranking,
            "elo_rating": round(self.elo_rating, 1),
            "is_host": self.is_host, "host_country": self.host_country,
            "confederation": self.confederation,
            "total_market_value": self.total_market_value,
            "avg_age": self.avg_age,
            "injury_impact_score": self.injury_impact_score,
            "home_advantage_bonus": self.home_advantage_bonus,
            "recent_form_score": self.recent_form_score,
        }


class TeamSquad(Base):
    __tablename__ = "team_squad"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    position = Column(String(5), nullable=False)  # GK/DEF/MID/FWD
    market_value = Column(Float, default=0.0)      # EUR
    is_starter = Column(Boolean, default=False)
    is_injured = Column(Boolean, default=False)
    injury_detail = Column(String(200), default="")
    injury_return_date = Column(String(20), default="")  # ISO date string
    importance_score = Column(Float, default=50.0)  # 0-100
    recent_form_score = Column(Float, default=50.0)  # 0-100

    team = relationship("Team", back_populates="squad")

    def to_dict(self):
        return {
            "id": self.id, "team_id": self.team_id, "name": self.name,
            "position": self.position, "market_value": self.market_value,
            "is_starter": self.is_starter, "is_injured": self.is_injured,
            "injury_detail": self.injury_detail,
            "importance_score": self.importance_score,
        }
