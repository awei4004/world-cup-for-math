"""Daily odds updater — fetch竞彩赔率 from accessible news sources."""
import re
import httpx
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.match import Match
from app.models.odds import Odds
from app.models.team import Team
from app.models.prediction import Prediction


class OddsUpdater:
    """Update match odds daily from news sources that quote 竞彩 official data."""

    # Known news sites that publish 竞彩 odds (accessible without JS)
    NEWS_SOURCES = [
        "finance.sina.cn",
    ]

    @staticmethod
    async def update_odds_from_json(db: AsyncSession, odds_data: List[Dict]) -> int:
        """
        Update odds from structured JSON data.

        Each entry: {
            "home_team": "墨西哥",    # Chinese team name
            "away_team": "南非",
            "win": 1.30,            # 胜赔率
            "draw": 3.92,           # 平赔率
            "lose": 7.85,           # 负赔率
            "handicap": -1,         # 让球数 (optional)
            "handicap_win": 2.00,   # 让球胜赔率 (optional)
            "handicap_draw": 3.25,  # 让球平赔率 (optional)
            "handicap_lose": 3.11,  # 让球负赔率 (optional)
        }
        Returns count of updated matches.
        """
        count = 0
        for entry in odds_data:
            # Find match by team names
            result = await db.execute(
                select(Match)
                .options(selectinload(Match.home_team), selectinload(Match.away_team))
                .where(Match.status.in_(["scheduled", "live"]))
            )
            matches = result.scalars().all()

            match = None
            for m in matches:
                if (m.home_team.name_cn == entry["home_team"] and
                    m.away_team.name_cn == entry["away_team"]):
                    match = m
                    break

            if not match:
                print(f"[Odds] Match not found: {entry['home_team']} vs {entry['away_team']}")
                continue

            # Upsert odds
            result = await db.execute(
                select(Odds).where(Odds.match_id == match.id)
            )
            odds = result.scalar_one_or_none()

            now = datetime.utcnow()
            if odds:
                odds.win_odds = entry["win"]
                odds.draw_odds = entry["draw"]
                odds.lose_odds = entry["lose"]
                odds.handicap = entry.get("handicap")
                odds.handicap_win = entry.get("handicap_win")
                odds.handicap_draw = entry.get("handicap_draw")
                odds.handicap_lose = entry.get("handicap_lose")
                odds.source = "竞彩官方"
                odds.updated_at = now
            else:
                odds = Odds(
                    match_id=match.id,
                    win_odds=entry["win"],
                    draw_odds=entry["draw"],
                    lose_odds=entry["lose"],
                    handicap=entry.get("handicap"),
                    handicap_win=entry.get("handicap_win"),
                    handicap_draw=entry.get("handicap_draw"),
                    handicap_lose=entry.get("handicap_lose"),
                    source="竞彩官方",
                    updated_at=now,
                )
                db.add(odds)

            count += 1
            print(f"[Odds] Updated: {entry['home_team']} vs {entry['away_team']}: "
                  f"胜{entry['win']} 平{entry['draw']} 负{entry['lose']}")

        if count > 0:
            await db.commit()
        return count

    @staticmethod
    async def fetch_from_sina(db: AsyncSession, match_date: str = None) -> int:
        """
        Try to fetch odds from finance.sina.cn articles.
        Searches for '世界杯竞彩湃' articles for the given date.
        """
        if not match_date:
            match_date = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")

        try:
            # Search cn.bing.com for sina articles
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://cn.bing.com/search",
                    params={
                        "q": f"site:finance.sina.cn 世界杯竞彩湃 {match_date}",
                        "setmkt": "zh-CN",
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                    },
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    # Extract article URLs from Bing results
                    urls = re.findall(
                        r'https?://finance\.sina\.cn/\d{4}-\d{2}-\d{2}/detail-[a-z0-9]+\.d\.html',
                        resp.text,
                    )
                    if urls:
                        # Fetch the first article
                        article_url = urls[0]
                        print(f"[Odds] Found article: {article_url}")
                        article_resp = await client.get(
                            article_url,
                            headers={"User-Agent": "Mozilla/5.0"},
                            follow_redirects=True,
                        )
                        if article_resp.status_code == 200:
                            odds_list = OddsUpdater._parse_sina_article(
                                article_resp.text
                            )
                            if odds_list:
                                return await OddsUpdater.update_odds_from_json(
                                    db, odds_list
                                )
        except Exception as e:
            print(f"[Odds] Sina fetch failed: {e}")

        return 0

    @staticmethod
    def _parse_sina_article(html: str) -> List[Dict]:
        """Parse odds data from a sina.cn '世界杯竞彩湃' article."""
        odds_list = []
        try:
            # Get all <p> tag content
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
            full_text = ' '.join(
                re.sub(r'<[^>]+>', '', p).strip() for p in paragraphs
            )

            # Find odds patterns: 3 decimal numbers separated by spaces
            # Typically looks like: "1.26   4.45   9.00" for 胜平负
            # And: "-1   2.00   3.25   3.11" for 让球
            odds_blocks = re.findall(
                r'(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})',
                full_text,
            )
            handicap_blocks = re.findall(
                r'([+-]?\d+)\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})',
                full_text,
            )

            # Match odds to teams mentioned in the article
            team_names = re.findall(r'(墨西哥|加拿大|美国|南非|韩国|捷克|波黑|巴拉圭|巴西|摩洛哥|海地|苏格兰|卡塔尔|瑞士|德国|库拉索|科特迪瓦|厄瓜多尔|荷兰|日本|瑞典|突尼斯|比利时|埃及|伊朗|新西兰|西班牙|佛得角|沙特阿拉伯|乌拉圭|法国|塞内加尔|伊拉克|挪威|阿根廷|阿尔及利亚|奥地利|约旦|葡萄牙|民主刚果|乌兹别克斯坦|哥伦比亚|英格兰|克罗地亚|加纳|巴拿马)', full_text)

            # Pair teams with odds blocks (heuristic: odds appear near team mentions)
            # This is a simplified parser; real implementation would need more context
            if len(odds_blocks) >= 2 and len(team_names) >= 4:
                for i in range(0, len(team_names) - 1, 2):
                    home = team_names[i]
                    away = team_names[i + 1]
                    block_idx = i // 2
                    if block_idx < len(odds_blocks):
                        w, d, l = odds_blocks[block_idx]
                        entry = {
                            "home_team": home,
                            "away_team": away,
                            "win": float(w),
                            "draw": float(d),
                            "lose": float(l),
                        }
                        # Add handicap if available
                        if block_idx < len(handicap_blocks):
                            hc, hw, hd, hl = handicap_blocks[block_idx]
                            entry["handicap"] = int(hc)
                            entry["handicap_win"] = float(hw)
                            entry["handicap_draw"] = float(hd)
                            entry["handicap_lose"] = float(hl)
                        odds_list.append(entry)
        except Exception as e:
            print(f"[Odds] Parse error: {e}")

        return odds_list
