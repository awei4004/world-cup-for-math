"""Betting optimizer — Kelly criterion + parlay optimization for 竞彩足球."""
import json
import itertools
from typing import List, Dict, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime

from app.models.match import Match
from app.models.odds import Odds
from app.models.prediction import Prediction, BetRecommendation, BetLedger
from app.services.odds_parser import OddsParser


class BetOptimizer:
    """Find value bets and optimal parlay combinations."""

    MAX_PARLAY = 4       # 体彩 max 4串1
    MAX_STAKE_PCT = 0.05  # 5% per bet
    MAX_DAILY_PCT = 0.20  # 20% daily
    MIN_ODDS = 1.50       # Minimum odds
    KELLY_FRACTION = 0.25 # 1/4 Kelly
    BANKROLL = 10000.0    # Starting bankroll

    def __init__(self, db: AsyncSession):
        self.db = db
        self.bankroll = self.BANKROLL

    async def optimize(self) -> Dict:
        """Run full optimization: find value bets and parlay combos."""
        # Get all scheduled matches with predictions and odds
        result = await self.db.execute(
            select(Match)
            .options(
                selectinload(Match.home_team),
                selectinload(Match.away_team),
                selectinload(Match.prediction),
                selectinload(Match.odds),
            )
            .where(Match.status == "scheduled")
            .order_by(Match.match_date)
            .limit(20)
        )
        matches = result.scalars().all()

        # Ensure we have odds for all matches
        for m in matches:
            if not m.odds:
                await OddsParser.update_odds_for_match(self.db, m.id)

        # Refresh matches with odds
        result = await self.db.execute(
            select(Match)
            .options(
                selectinload(Match.home_team),
                selectinload(Match.away_team),
                selectinload(Match.prediction),
                selectinload(Match.odds),
            )
            .where(Match.status == "scheduled")
            .order_by(Match.match_date)
            .limit(20)
        )
        matches = [m for m in result.scalars().all()
                   if m.prediction and m.odds]

        # === STEP 1: Find value bets (EV > 0) ===
        value_bets = []
        for m in matches:
            for selection, result_key in [("主胜", "home"), ("平局", "draw"), ("客胜", "away")]:
                ev, pred_prob, imp_prob, odds_val = self._evaluate_bet(m, result_key)
                if ev > 0 and odds_val >= self.MIN_ODDS:
                    value_bets.append({
                        "match": m,
                        "selection": selection,
                        "result_key": result_key,
                        "odds": odds_val,
                        "predicted_prob": pred_prob,
                        "implied_prob": imp_prob,
                        "ev": ev,
                        "kelly": self._kelly_fraction(pred_prob, odds_val),
                    })

        # Sort by EV descending
        value_bets.sort(key=lambda x: x["ev"], reverse=True)

        # === STEP 2: Generate single bets (单关) ===
        await self._clear_old_recommendations()
        singles = value_bets[:10]
        for bet in singles:
            stake = self._calculate_stake(bet["kelly"])
            rec = BetRecommendation(
                created_at=datetime.utcnow(),
                strategy_name=f"{bet['match'].home_team.name_cn} vs {bet['match'].away_team.name_cn} — {bet['selection']}",
                matches_json=json.dumps([{
                    "match_id": bet["match"].id,
                    "home_team": bet["match"].home_team.name_cn,
                    "away_team": bet["match"].away_team.name_cn,
                    "selection": bet["selection"],
                    "odds": bet["odds"],
                    "predicted_prob": round(bet["predicted_prob"], 4),
                }], ensure_ascii=False),
                bet_type="单关",
                total_odds=round(bet["odds"], 2),
                expected_value=round(bet["ev"], 4),
                kelly_fraction=round(bet["kelly"], 4),
                suggested_stake=round(stake, 2),
                explanation=self._explain_bet(bet),
            )
            self.db.add(rec)

        # === STEP 3: Generate parlay combos (混合过关) ===
        parlays = self._generate_parlays(value_bets[:15])
        for p in parlays:
            rec = BetRecommendation(
                created_at=datetime.utcnow(),
                strategy_name=p["name"],
                matches_json=json.dumps(p["matches"], ensure_ascii=False),
                bet_type=p["type"],
                total_odds=round(p["total_odds"], 2),
                expected_value=round(p["ev"], 4),
                kelly_fraction=round(p["kelly"], 4),
                suggested_stake=round(p["stake"], 2),
                explanation=p["explanation"],
            )
            self.db.add(rec)

        await self.db.commit()

        return {
            "value_bets_count": len(singles),
            "parlay_count": len(parlays),
            "total_bets": len(singles) + len(parlays),
            "bankroll": self.bankroll,
        }

    def _evaluate_bet(self, match, result_key: str) -> Tuple[float, float, float, float]:
        """Calculate EV for a bet. Returns (ev, pred_prob, implied_prob, odds_val)."""
        if not match.prediction or not match.odds:
            return 0, 0, 0, 1.0

        probs = {
            "home": match.prediction.prob_home_win,
            "draw": match.prediction.prob_draw,
            "away": match.prediction.prob_away_win,
        }
        odds_vals = {
            "home": match.odds.win_odds,
            "draw": match.odds.draw_odds,
            "away": match.odds.lose_odds,
        }

        pred_prob = probs.get(result_key, 0)
        odds_val = odds_vals.get(result_key, 1.0)

        if not odds_val or odds_val <= 1.0:
            return 0, pred_prob, 0, 1.0

        imp = OddsParser.implied_probability(
            odds_vals["home"], odds_vals["draw"], odds_vals["away"]
        )
        imp_prob = imp.get(result_key, 0)

        ev = pred_prob * (odds_val - 1) - (1 - pred_prob) * 1.0
        return ev, pred_prob, imp_prob, odds_val

    def _kelly_fraction(self, prob: float, odds: float) -> float:
        """Kelly Criterion: f* = (p*b - 1) / (b - 1)."""
        if odds <= 1.0:
            return 0
        b = odds - 1  # Decimal odds to fractional
        kelly = (prob * b - (1 - prob)) / b
        return max(0, kelly * self.KELLY_FRACTION)

    def _calculate_stake(self, kelly: float) -> float:
        """Calculate suggested stake from Kelly fraction."""
        stake = self.bankroll * kelly
        return min(stake, self.bankroll * self.MAX_STAKE_PCT)

    def _generate_parlays(self, value_bets: List[dict]) -> List[dict]:
        """Generate optimal parlay combinations."""
        results = []

        # 2串1 combos
        for b1, b2 in itertools.combinations(value_bets, 2):
            if b1["match"].id == b2["match"].id:
                continue

            total_odds = b1["odds"] * b2["odds"]
            if total_odds < self.MIN_ODDS:
                continue

            combined_prob = b1["predicted_prob"] * b2["predicted_prob"]
            ev = combined_prob * (total_odds - 1) - (1 - combined_prob)
            kelly = self._kelly_fraction(combined_prob, total_odds)
            stake = self._calculate_stake(kelly)

            if ev > 0.02:  # Minimum 2% EV
                results.append({
                    "name": f"2串1: {b1['selection']}+{b2['selection']}",
                    "type": "2串1",
                    "matches": [
                        {"match_id": b1["match"].id, "home_team": b1["match"].home_team.name_cn,
                         "away_team": b1["match"].away_team.name_cn, "selection": b1["selection"],
                         "odds": b1["odds"], "predicted_prob": round(b1["predicted_prob"], 4)},
                        {"match_id": b2["match"].id, "home_team": b2["match"].home_team.name_cn,
                         "away_team": b2["match"].away_team.name_cn, "selection": b2["selection"],
                         "odds": b2["odds"], "predicted_prob": round(b2["predicted_prob"], 4)},
                    ],
                    "total_odds": total_odds,
                    "ev": ev,
                    "kelly": kelly,
                    "stake": stake,
                    "explanation": self._explain_parlay(b1, b2, total_odds, combined_prob, ev),
                })

        # Sort by EV, keep top 5
        results.sort(key=lambda x: x["ev"], reverse=True)
        return results[:5]

    def _explain_bet(self, bet: dict) -> str:
        """Generate explanation for a single bet."""
        edge = (bet["predicted_prob"] - bet["implied_prob"]) * 100
        return (
            f"模型预测概率 {bet['predicted_prob']:.1%} > 市场隐含概率 {bet['implied_prob']:.1%}，"
            f"优势 {edge:.1f}%。期望值 +{bet['ev']*100:.2f}%"
        )

    def _explain_parlay(self, b1, b2, total_odds, combined_prob, ev) -> str:
        """Generate explanation for a parlay."""
        return (
            f"组合概率 {combined_prob:.4%}，组合赔率 {total_odds:.2f}。"
            f"两场均存在价值投注机会，合并后期望值 +{ev*100:.2f}%"
        )

    async def _clear_old_recommendations(self):
        """Remove old recommendations from the database."""
        from sqlalchemy import delete
        await self.db.execute(delete(BetRecommendation))
        await self.db.flush()

    async def get_recommendations(self) -> dict:
        """Get current recommendations with real bankroll."""
        result = await self.db.execute(
            select(BetRecommendation)
            .order_by(BetRecommendation.expected_value.desc())
            .limit(15)
        )
        recs = result.scalars().all()
        summary = await self.get_bankroll_summary()
        return {
            "recommendations": [r.to_dict() for r in recs],
            "bankroll": summary["bankroll"],
            "daily_bet": summary["today_staked"],
            "profit": summary["total_profit"],
        }

    async def place_bet(self, recommendation_id: int) -> dict:
        """Record a bet in the ledger from a recommendation."""
        result = await self.db.execute(
            select(BetRecommendation).where(BetRecommendation.id == recommendation_id)
        )
        rec = result.scalar_one_or_none()
        if not rec:
            return {"error": "Recommendation not found"}

        matches = rec.get_matches()
        if not matches:
            return {"error": "No matches in recommendation"}

        # Record one ledger entry per match in the bet
        entries = []
        for m in matches:
            entry = BetLedger(
                recommendation_id=rec.id,
                match_id=m.get("match_id", 0),
                bet_type=rec.bet_type,
                selection=m.get("selection", ""),
                stake=rec.suggested_stake / len(matches) if rec.bet_type != "单关" else rec.suggested_stake,
                odds=m.get("odds", rec.total_odds),
                result="pending",
            )
            self.db.add(entry)
            entries.append(entry)

        await self.db.commit()
        summary = await self.get_bankroll_summary()
        return {
            "status": "ok",
            "placed": len(entries),
            "total_stake": sum(e.stake for e in entries),
            "bankroll": summary["bankroll"],
            "today_staked": summary["today_staked"],
            "today_remaining": summary["today_remaining"],
        }

    async def get_bankroll_summary(self) -> dict:
        """Calculate real bankroll from ledger."""
        INITIAL = 10000.0
        DAILY_LIMIT = 2000.0

        # Total profit from settled bets
        result = await self.db.execute(
            select(BetLedger).where(BetLedger.result.in_(["won", "lost"]))
        )
        settled = result.scalars().all()

        total_profit = sum(b.profit for b in settled)

        # Today's staked amount (Beijing time)
        from datetime import datetime, timedelta
        now_bj = datetime.utcnow() + timedelta(hours=8)
        today_start = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start - timedelta(hours=8)

        result = await self.db.execute(
            select(BetLedger).where(BetLedger.created_at >= today_start_utc)
        )
        today_bets = result.scalars().all()
        today_staked = sum(b.stake for b in today_bets)

        # Count pending bets
        result = await self.db.execute(
            select(BetLedger).where(BetLedger.result == "pending")
        )
        pending = result.scalars().all()
        pending_count = len(pending)
        pending_stake = sum(b.stake for b in pending)

        return {
            "bankroll": round(INITIAL + total_profit, 2),
            "initial": INITIAL,
            "total_profit": round(total_profit, 2),
            "today_staked": round(today_staked, 2),
            "today_remaining": round(max(0, DAILY_LIMIT - today_staked), 2),
            "daily_limit": DAILY_LIMIT,
            "pending_count": pending_count,
            "pending_stake": round(pending_stake, 2),
            "settled_count": len(settled),
        }

    @staticmethod
    async def settle_bets_for_match(db: AsyncSession, match_id: int,
                                     home_score: int, away_score: int):
        """Settle all pending bets for a finished match."""
        from sqlalchemy import update

        result = await db.execute(
            select(BetLedger).where(
                BetLedger.match_id == match_id,
                BetLedger.result == "pending",
            )
        )
        pending = result.scalars().all()

        for bet in pending:
            # Determine if bet won
            if home_score > away_score:
                winner = "主胜"
            elif away_score > home_score:
                winner = "客胜"
            else:
                winner = "平局"

            if bet.selection == winner:
                bet.result = "won"
                bet.profit = bet.stake * (bet.odds - 1)
            else:
                bet.result = "lost"
                bet.profit = -bet.stake

            bet.settled_at = datetime.utcnow()
            print(f"[BetLedger] Settled bet #{bet.id}: {bet.selection} {bet.result} "
                  f"(stake={bet.stake:.0f}, profit={bet.profit:.0f})")

        if pending:
            await db.commit()
            print(f"[BetLedger] {len(pending)} bets settled for match #{match_id}")

        return len(pending)
