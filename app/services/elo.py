"""Elo rating system for FIFA World Cup teams."""
import math
from typing import Tuple


class EloService:
    """Elo rating system with World Cup-specific adjustments."""

    K_FACTOR = 60        # World Cup K-factor (higher = more responsive)
    HOME_ADVANTAGE = 100 # Base home advantage in Elo points
    HOST_BONUS = 80      # Additional bonus for host nation
    LEAGUE_AVG_GOALS = 1.35  # Average goals per team in international football

    @staticmethod
    def expected_result(elo_a: float, elo_b: float) -> float:
        """Probability that team A beats team B."""
        return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))

    @staticmethod
    def win_probability(elo_home: float, elo_away: float, home_bonus: float = 0) -> Tuple[float, float, float]:
        """
        Calculate win/draw/loss probabilities using Elo difference.

        Returns (prob_home_win, prob_draw, prob_away_win).
        Draw probability is modeled as a function of how close the teams are.
        """
        adjusted_elo_home = elo_home + EloService.HOME_ADVANTAGE + home_bonus
        diff = adjusted_elo_home - elo_away

        # Home win probability from Elo expected result
        p_home = EloService.expected_result(adjusted_elo_home, elo_away)

        # Draw probability: peaks when teams are equal, decays with Elo difference
        draw_peak = 0.28  # Max draw probability when teams are perfectly matched
        draw_sigma = 200  # How fast draw probability decays with Elo difference
        p_draw = draw_peak * math.exp(-(diff ** 2) / (2 * draw_sigma ** 2))

        # Adjust win/loss to accommodate draw
        p_home = p_home * (1 - p_draw)
        p_away = (1 - p_home - p_draw)

        return p_home, p_draw, p_away

    @staticmethod
    def expected_goals(elo_team: float, elo_opponent: float,
                       home_bonus: float = 0) -> float:
        """
        Calculate expected goals using a calibrated linear model.
        Based on real international football data:
        - Equal teams: ~1.35 xG each
        - 200 Elo advantage: ~1.80 vs 0.90
        - 400 Elo advantage: ~2.30 vs 0.60
        """
        effective_elo = elo_team + home_bonus
        diff = effective_elo - elo_opponent

        # Linear xG model: more stable than exponential
        # Every 100 Elo points ≈ +0.25 xG
        xg = EloService.LEAGUE_AVG_GOALS + diff / 400.0

        # Soft cap: apply diminishing returns for large Elo differences
        if xg > 2.5:
            xg = 2.5 + (xg - 2.5) * 0.3  # Diminishing returns above 2.5
        if xg > 3.5:
            xg = 3.5  # Hard cap at 3.5 xG

        return max(xg, 0.15)

    @staticmethod
    def update_elo(winner_elo: float, loser_elo: float,
                   goal_difference: int, is_draw: bool = False,
                   k: float = None) -> Tuple[float, float]:
        """
        Update Elo ratings after a match.

        - K-factor is modulated by goal difference (big wins = bigger Elo swing)
        - Draws result in smaller Elo transfer
        """
        if k is None:
            k = EloService.K_FACTOR

        expected_win = EloService.expected_result(winner_elo, loser_elo)

        # Goal difference multiplier (diminishing returns after 4 goals)
        margin_multiplier = min(abs(goal_difference), 4) ** 0.5

        if is_draw:
            # Draw: half the Elo transfer
            transfer = k * 0.5 * (0.5 - expected_win)
            new_winner = winner_elo + transfer
            new_loser = loser_elo - transfer
        else:
            transfer = k * margin_multiplier * (1.0 - expected_win)
            new_winner = winner_elo + transfer
            new_loser = loser_elo - transfer * 0.85  # Loser loses slightly less

        return round(new_winner, 1), round(new_loser, 1)

    @staticmethod
    def fifa_rank_to_elo(fifa_rank: int) -> float:
        """Convert FIFA ranking to approximate Elo rating."""
        if fifa_rank <= 0:
            return 1500.0
        # Approximate: rank 1 ~ 2150, rank 50 ~ 1700, rank 200 ~ 1200
        return max(2150 - (fifa_rank - 1) * 10, 1200.0)

    @staticmethod
    def get_home_bonus(is_host: bool, host_country: str, match_country: str,
                       confederation: str) -> float:
        """
        Calculate home advantage bonus for a team.

        L1: Host playing in their own country → +100 Elo
        L2: Host playing in co-host country → +50 Elo
        L3: CONCACAF team at neutral venue → +30 Elo
        """
        if is_host:
            if match_country.upper() == host_country.upper():
                return 100.0  # L1: Home country
            elif match_country.upper() in ("USA", "CAN", "MEX"):
                return 50.0   # L2: Co-host country
            else:
                return 30.0   # L3: Regional advantage
        elif confederation == "CONCACAF":
            return 30.0       # Regional familiarity bonus
        return 0.0
