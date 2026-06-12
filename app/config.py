"""Application configuration."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SEED_DIR = DATA_DIR / "seed"
HISTORICAL_DIR = DATA_DIR / "historical"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR}/worldcup.db")
DATABASE_URL_SYNC = os.getenv("DATABASE_URL_SYNC", f"sqlite:///{BASE_DIR}/worldcup.db")

# World Cup 2026
WORLD_CUP_START = "2026-06-11"
WORLD_CUP_END = "2026-07-19"
TOTAL_MATCHES = 104  # 48 teams → 104 matches total

# Elo config
ELO_K_FACTOR = 60
ELO_HOME_ADVANTAGE = 100
ELO_HOST_BONUS = 80
LEAGUE_AVG_GOALS = 1.35  # Average goals per team per match

# Model ensemble weights (dynamic, these are starting values)
ELO_WEIGHT = 0.35
POISSON_WEIGHT = 0.25
XGBOOST_WEIGHT = 0.40

# Betting
MAX_STAKE_PCT = 0.05       # Max 5% per single bet
MAX_DAILY_STAKE_PCT = 0.20 # Max 20% of bankroll per day
MIN_ODDS = 1.50            # Minimum odds to consider
MAX_PARLAY = 4             # Max teams in parlay (体彩 limit)
KELLY_FRACTION = 0.25      # 1/4 Kelly for safety
STOP_LOSS_STREAK = 3       # After 3 consecutive losses, reduce to 1/8 Kelly
STOP_LOSS_FRACTION = 0.125 # 1/8 Kelly after stop-loss triggered

# Scraping
ODDS_UPDATE_INTERVAL = 300   # 5 minutes
SCORE_UPDATE_INTERVAL = 120  # 2 minutes
INJURY_UPDATE_INTERVAL = 7200 # 2 hours
SQUAD_VALUE_UPDATE_INTERVAL = 86400 # 24 hours

# APIs (set via env vars)
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
