"""External factors evaluation — weather, travel, altitude, motivation."""
import math
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.match import Match
from app.models.team import Team
from app.models.external_factors import ExternalFactors


class ExternalFactorsService:
    """Evaluate and store external factors for each match."""

    # Travel fatigue: km -> fatigue points
    TRAVEL_FATIGUE_PER_1000KM = 5.0
    TIMEZONE_FATIGUE_PER_HOUR = 2.0

    # Weather impact thresholds
    HIGH_TEMP = 30.0       # Celsius — affects European teams
    HIGH_HUMIDITY = 70.0    # % — affects running
    HIGH_ALTITUDE = 1500.0  # meters — affects oxygen

    # Default June temperatures for host cities (°C)
    CITY_TEMPS = {
        "Mexico City": 22, "Guadalajara": 26, "Monterrey": 32,
        "Toronto": 22, "Vancouver": 18,
        "Los Angeles": 24, "San Francisco": 18, "Seattle": 19,
        "Dallas": 32, "Houston": 33, "Kansas City": 28,
        "Atlanta": 29, "Miami": 31, "Boston": 22,
        "Philadelphia": 25, "NY/NJ": 26,
    }
    CITY_WEATHER = {
        "Miami": "雨", "Houston": "晴", "Dallas": "晴",
        "Atlanta": "晴", "Seattle": "阴", "Vancouver": "阴",
        "Toronto": "晴", "Boston": "晴", "Philadelphia": "晴",
        "NY/NJ": "晴", "Los Angeles": "晴", "San Francisco": "晴",
        "Kansas City": "晴", "Mexico City": "雨", "Guadalajara": "晴",
        "Monterrey": "晴",
    }
    CITY_HUMIDITY = {
        "Miami": 75, "Houston": 70, "Dallas": 55,
        "Atlanta": 65, "Seattle": 60, "Vancouver": 65,
        "Toronto": 55, "Boston": 60, "Philadelphia": 58,
        "NY/NJ": 60, "Los Angeles": 50, "San Francisco": 55,
        "Kansas City": 60, "Mexico City": 50, "Guadalajara": 45,
        "Monterrey": 65,
    }

    @staticmethod
    def estimate_temperature(city: str) -> float:
        return ExternalFactorsService.CITY_TEMPS.get(city, 25.0)

    @staticmethod
    def estimate_humidity(city: str) -> float:
        return ExternalFactorsService.CITY_HUMIDITY.get(city, 60.0)

    @staticmethod
    def estimate_weather(city: str) -> str:
        return ExternalFactorsService.CITY_WEATHER.get(city, "晴")

    @staticmethod
    def calculate_travel_fatigue(distance_km: float, timezone_diff: float,
                                  consecutive_away: int = 0) -> float:
        """Calculate travel fatigue score (0-100)."""
        fatigue = (distance_km / 1000.0) * ExternalFactorsService.TRAVEL_FATIGUE_PER_1000KM
        fatigue += abs(timezone_diff) * ExternalFactorsService.TIMEZONE_FATIGUE_PER_HOUR
        fatigue += consecutive_away * 5.0
        return min(fatigue, 100.0)

    @staticmethod
    def calculate_weather_impact(temp: float, humidity: float, weather: str,
                                   confederation: str) -> float:
        """
        Calculate weather impact on a team (-10 to +10).
        European teams struggle in heat/humidity.
        """
        impact = 0.0

        # Heat impact
        if temp > ExternalFactorsService.HIGH_TEMP:
            heat_penalty = (temp - ExternalFactorsService.HIGH_TEMP) * 0.3
            if confederation == "UEFA":
                heat_penalty *= 1.5  # European teams suffer more
            elif confederation in ("CAF", "CONCACAF", "AFC"):
                heat_penalty *= 0.5  # Used to heat
            impact -= heat_penalty

        # Humidity impact
        if humidity > ExternalFactorsService.HIGH_HUMIDITY:
            humidity_penalty = (humidity - ExternalFactorsService.HIGH_HUMIDITY) * 0.1
            if confederation == "UEFA":
                humidity_penalty *= 1.3
            impact -= humidity_penalty

        # Rain increases randomness (slight negative for favorites)
        if weather == "雨":
            impact -= 1.0

        return max(-10.0, min(10.0, impact))

    @staticmethod
    def calculate_altitude_advantage(altitude: float, team_confederation: str) -> float:
        """Calculate altitude advantage (0-100)."""
        if altitude < ExternalFactorsService.HIGH_ALTITUDE:
            return 0.0

        # At high altitude, CONMEBOL teams adapt better
        altitude_factor = (altitude - ExternalFactorsService.HIGH_ALTITUDE) / 100.0
        advantage = min(altitude_factor * 5, 80.0)

        if team_confederation in ("CONMEBOL", "CONCACAF"):
            return advantage * 0.5  # Less affected
        elif team_confederation == "UEFA":
            return advantage  # Most affected
        return advantage * 0.7

    @staticmethod
    def calculate_motivation(stage: str, matchday: int,
                              is_crucial: bool = False) -> float:
        """Calculate motivation factor (0-100)."""
        base = 70.0

        if stage == "小组赛":
            if matchday == 3:
                base = 95.0  # Final group match — everything on the line
            elif matchday == 1:
                base = 75.0  # Opening match
            else:
                base = 80.0
        elif stage in ("1/16决赛", "1/8决赛"):
            base = 90.0  # Knockout pressure
        elif stage in ("1/4决赛", "半决赛"):
            base = 95.0
        elif stage == "决赛":
            base = 100.0
        elif stage == "季军赛":
            base = 60.0  # 3rd place match — less motivation

        if is_crucial:
            base = min(base + 10, 100)

        return base

    @staticmethod
    async def evaluate_match(db: AsyncSession, match_id: int) -> ExternalFactors:
        """Evaluate all external factors for a match."""
        result = await db.execute(
            select(Match).where(Match.id == match_id)
        )
        match = result.scalar_one_or_none()
        if not match:
            return None

        home = await db.get(Team, match.home_team_id)
        away = await db.get(Team, match.away_team_id)

        # Weather
        temp = match.temperature or ExternalFactorsService.estimate_temperature(match.city)
        humidity = match.humidity or ExternalFactorsService.estimate_humidity(match.city)
        weather = match.weather or ExternalFactorsService.estimate_weather(match.city)

        weather_home = ExternalFactorsService.calculate_weather_impact(
            temp, humidity, weather, home.confederation
        )
        weather_away = ExternalFactorsService.calculate_weather_impact(
            temp, humidity, weather, away.confederation
        )

        # Altitude
        altitude = match.altitude or 0
        alt_adv = ExternalFactorsService.calculate_altitude_advantage(
            altitude, away.confederation
        )

        # Crowd support (host teams get more fans)
        crowd = 50.0
        if home.is_host:
            crowd = 85.0
        elif home.confederation == "CONCACAF":
            crowd = 60.0

        # Motivation
        motivation = ExternalFactorsService.calculate_motivation(
            match.stage, match.matchday
        )

        # Market sentiment: derive from odds vs model
        sentiment = 0.0
        try:
            from app.models.odds import Odds
            from app.models.prediction import Prediction
            odds_result = await db.execute(select(Odds).where(Odds.match_id == match_id))
            odds = odds_result.scalar_one_or_none()
            pred_result = await db.execute(select(Prediction).where(Prediction.match_id == match_id))
            pred = pred_result.scalar_one_or_none()
            if odds and pred and odds.source == '竞彩官方':
                # Market overvalues home team → positive sentiment
                market_home = (1/odds.win_odds) / (1/odds.win_odds + 1/odds.draw_odds + 1/odds.lose_odds)
                model_home = pred.prob_home_win
                sentiment = round(market_home - model_home, 4)  # -1 to +1
        except Exception:
            pass

        # Check if existing factors record
        result = await db.execute(
            select(ExternalFactors).where(ExternalFactors.match_id == match_id)
        )
        factors = result.scalar_one_or_none()

        if factors:
            factors.weather_impact_home = round(weather_home, 1)
            factors.weather_impact_away = round(weather_away, 1)
            factors.altitude_advantage = round(alt_adv, 1)
            factors.home_crowd_support = crowd
            factors.motivation_factor = motivation
            factors.betting_market_sentiment = sentiment
        else:
            factors = ExternalFactors(
                match_id=match_id,
                weather_impact_home=round(weather_home, 1),
                weather_impact_away=round(weather_away, 1),
                altitude_advantage=round(alt_adv, 1),
                home_crowd_support=crowd,
                motivation_factor=motivation,
                betting_market_sentiment=sentiment,
            )
            db.add(factors)

        await db.flush()
        return factors
