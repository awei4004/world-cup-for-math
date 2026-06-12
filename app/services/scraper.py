"""Dongqiudi data scraper — live scores, results, injuries."""
import json
import httpx
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.match import Match
from app.models.team import Team
from app.models.prediction import Prediction, MatchResult


class DongqiudiScraper:
    """Scrape live match data from FIFA API, Dongqiudi and other sources."""

    BASE_URL = "https://dongqiudi.com"
    API_BASE = "https://www.dongqiudi.com"
    FIFA_API = "https://api.fifa.com/api/v3/calendar/matches"

    # FIFA API MatchStatus codes
    FIFA_STATUS_MAP = {0: "finished", 1: "scheduled", 3: "live"}

    @staticmethod
    async def fetch_live_scores(db: AsyncSession) -> List[Dict]:
        """
        Fetch live match scores from multiple sources.
        Tries FIFA API first (most reliable), then Dongqiudi fallback.

        Returns list of updates applied (for logging).
        """
        updates = []

        # Method 1: FIFA API (primary, reliable)
        updates = await DongqiudiScraper._fetch_fifa_scores(db)

        # Method 2: Dongqiudi API (fallback, often blocked)
        if not updates:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://dongqiudi.com/api/v3/competition/1/matches",
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Accept": "application/json",
                        },
                        follow_redirects=True,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict) and "data" in data:
                            raw = DongqiudiScraper._extract_scores(data["data"])
                            for u in raw:
                                await DongqiudiScraper._apply_score_update(db, u)
                            updates = raw
            except Exception as e:
                print(f"[Scraper] Dongqiudi fetch: {e}")

        return updates

    @staticmethod
    async def _fetch_fifa_scores(db: AsyncSession) -> List[Dict]:
        """
        Fetch World Cup match scores from FIFA API.

        Returns list of update dicts applied.
        """
        updates = []
        try:
            now_utc = datetime.utcnow()
            from_date = (now_utc - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
            to_date = (now_utc + timedelta(days=4)).strftime("%Y-%m-%dT00:00:00Z")

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    DongqiudiScraper.FIFA_API,
                    params={
                        "from": from_date,
                        "to": to_date,
                        "count": 50,
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "application/json",
                    },
                    follow_redirects=True,
                )
                if resp.status_code != 200:
                    print(f"[Scraper] FIFA API returned {resp.status_code}")
                    return updates

                data = resp.json()
                results = data.get("Results", [])

                for r in results:
                    comp = r.get("CompetitionName", [{}])[0].get("Description", "")
                    if "World Cup" not in comp:
                        continue

                    home = r.get("Home", {})
                    away = r.get("Away", {})
                    home_code = home.get("IdCountry", "")
                    away_code = away.get("IdCountry", "")
                    home_name = home.get("TeamName", [{}])[0].get("Description", "")
                    away_name = away.get("TeamName", [{}])[0].get("Description", "")
                    raw_status = r.get("MatchStatus", 1)
                    status = DongqiudiScraper.FIFA_STATUS_MAP.get(raw_status, "scheduled")

                    home_score = r.get("HomeTeamScore")
                    away_score = r.get("AwayTeamScore")

                    # Skip matches with no score changes (not yet started)
                    if home_score is None and away_score is None:
                        continue

                    print(f"[Scraper/FIFA] {home_name} {home_score}-{away_score} {away_name} ({status})")

                    # Parse FIFA date for time-based matching
                    fifa_date_str = r.get("Date", "")
                    fifa_dt = None
                    if fifa_date_str:
                        try:
                            fifa_dt = datetime.strptime(
                                fifa_date_str.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z"
                            )
                        except ValueError:
                            pass

                    # Match by FIFA country code + date proximity (avoids knockout placeholders)
                    result = await db.execute(
                        select(Match)
                        .options(selectinload(Match.home_team), selectinload(Match.away_team))
                        .where(
                            Match.home_team.has(fifa_code=home_code),
                            Match.away_team.has(fifa_code=away_code),
                            Match.status.in_(["scheduled", "live"]),
                        )
                    )
                    candidates = result.scalars().all()

                    # Pick the match closest in date to the FIFA-reported date
                    match = None
                    if candidates:
                        if fifa_dt:
                            best_diff = timedelta(days=999)
                            fifa_naive = fifa_dt.replace(tzinfo=None)
                            for c in candidates:
                                diff = abs(c.match_date - fifa_naive)
                                if diff < best_diff:
                                    best_diff = diff
                                    match = c
                            # Safety: reject if date diff > 2 days (likely placeholder match)
                            if best_diff > timedelta(days=2):
                                print(f"[Scraper/FIFA] Skipping {home_name} vs {away_name}: no close match found (best diff={best_diff})")
                                continue
                        else:
                            match = candidates[0]  # fallback: first candidate

                    if match:
                        await DongqiudiScraper._update_match_score(
                            db, match, home_score, away_score, status
                        )
                        updates.append({
                            "match_id": match.id,
                            "home_score": home_score,
                            "away_score": away_score,
                            "status": status,
                        })

        except Exception as e:
            print(f"[Scraper] FIFA API error: {e}")

        return updates

    @staticmethod
    def _parse_embedded_json(html: str) -> Optional[dict]:
        """Parse __INITIAL_STATE__ JSON from Dongqiudi HTML."""
        try:
            start = html.find("window.__INITIAL_STATE__=")
            if start == -1:
                return None
            start = html.find("{", start)
            if start == -1:
                return None

            depth = 0
            end = start
            for i in range(start, len(html)):
                if html[i] == "{":
                    depth += 1
                elif html[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

            json_str = html[start:end]
            return json.loads(json_str)
        except Exception:
            return None

    @staticmethod
    def _extract_scores(data: dict) -> List[Dict]:
        """Extract match scores from Dongqiudi data structure."""
        updates = []
        try:
            # Dongqiudi structure varies; try common paths
            matches_data = (
                data.get("matchList") or
                data.get("matches") or
                data.get("scheduleData", {}).get("matches") or
                []
            )

            for m in matches_data:
                home_score = m.get("home_score") or m.get("score_a")
                away_score = m.get("away_score") or m.get("score_b")
                status = m.get("status") or m.get("match_status", "scheduled")

                # Map Dongqiudi status codes
                if status in ("live", "playing", "1", 1):
                    status = "live"
                elif status in ("finished", "ft", "3", 3):
                    status = "finished"
                else:
                    status = "scheduled"

                updates.append({
                    "dongqiudi_id": m.get("id") or m.get("match_id"),
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": status,
                    "home_team_name": m.get("team_A_name") or m.get("home_team"),
                    "away_team_name": m.get("team_B_name") or m.get("away_team"),
                })
        except Exception as e:
            print(f"[Scraper] Score extraction error: {e}")

        return updates

    @staticmethod
    async def _apply_score_update(db: AsyncSession, update: Dict):
        """Apply a score update to the database."""
        # Try to find match by team names
        home_name = update.get("home_team_name", "")
        away_name = update.get("away_team_name", "")

        if home_name and away_name:
            result = await db.execute(
                select(Match)
                .options(selectinload(Match.home_team), selectinload(Match.away_team))
                .where(Match.status.in_(["scheduled", "live"]))
            )
            matches = result.scalars().all()

            for m in matches:
                if (m.home_team.name_cn == home_name and
                    m.away_team.name_cn == away_name):
                    await DongqiudiScraper._update_match_score(
                        db, m, update["home_score"],
                        update["away_score"], update["status"]
                    )
                    break

    @staticmethod
    async def _update_match_score(db: AsyncSession, match: Match,
                                   home_score: int, away_score: int, status: str):
        """Update match score and trigger downstream updates."""
        if match.home_score == home_score and match.away_score == away_score and match.status == status:
            return  # No change

        match.home_score = home_score
        match.away_score = away_score
        match.status = status
        await db.flush()

        print(f"[Scraper] Updated: {match.home_team.name_cn} {home_score}-{away_score} {match.away_team.name_cn}")

        # If match finished, update Elo and regenerate predictions
        if status == "finished":
            from app.services.elo import EloService
            from app.services.predictor import PredictionEngine
            from app.models.prediction import MatchResult

            # Determine winner
            if home_score > away_score:
                winner, loser = match.home_team, match.away_team
                goal_diff = home_score - away_score
                is_draw = False
            elif away_score > home_score:
                winner, loser = match.away_team, match.home_team
                goal_diff = away_score - home_score
                is_draw = False
            else:
                # Draw
                winner, loser = match.home_team, match.away_team
                goal_diff = 0
                is_draw = True

            # Update Elo
            new_win, new_lose = EloService.update_elo(
                winner.elo_rating, loser.elo_rating, goal_diff, is_draw
            )
            winner.elo_rating = new_win
            loser.elo_rating = new_lose
            await db.flush()

            # Record result
            result = MatchResult(
                match_id=match.id,
                actual_home_score=home_score,
                actual_away_score=away_score,
            )
            db.add(result)
            await db.commit()

            print(f"[Scraper] Elo updated: {winner.name_cn} {new_win}, {loser.name_cn} {new_lose}")

            # Settle bets for this match
            from app.services.bet_optimizer import BetOptimizer
            await BetOptimizer.settle_bets_for_match(db, match.id, home_score, away_score)

            # Regenerate predictions for remaining matches
            engine = PredictionEngine(db)
            remaining = await db.execute(
                select(Match).where(Match.status == "scheduled").limit(30)
            )
            for m in remaining.scalars().all():
                try:
                    await engine.predict_match(m.id)
                except Exception:
                    pass
            print(f"[Scraper] Predictions regenerated")
        else:
            # Live or other status — still need to commit the score update
            await db.commit()

    @staticmethod
    async def fetch_injury_news(db: AsyncSession) -> List[Dict]:
        """Search for latest injury news from Dongqiudi."""
        injuries = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{DongqiudiScraper.API_BASE}/global/2026-worldcup",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if resp.status_code == 200:
                    text = resp.text
                    # Look for injury-related keywords
                    keywords = ["伤病", "受伤", "伤缺", "缺席", "injury", "injured"]
                    for kw in keywords:
                        if kw in text.lower():
                            # Extract surrounding text
                            idx = text.lower().find(kw.lower())
                            snippet = text[max(0, idx-100):idx+200]
                            injuries.append({"keyword": kw, "snippet": snippet[:150]})
        except Exception as e:
            print(f"[Scraper] Injury fetch failed: {e}")

        return injuries

    @staticmethod
    async def manual_score_update(db: AsyncSession, match_id: int,
                                   home_score: int, away_score: int) -> Dict:
        """Manual score update via admin panel."""
        result = await db.execute(
            select(Match).options(
                selectinload(Match.home_team), selectinload(Match.away_team)
            ).where(Match.id == match_id)
        )
        match = result.scalar_one_or_none()
        if not match:
            return {"error": "Match not found"}

        await DongqiudiScraper._update_match_score(
            db, match, home_score, away_score, "finished"
        )
        return {"status": "ok", "match_id": match_id}
