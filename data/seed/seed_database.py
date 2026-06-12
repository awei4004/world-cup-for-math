"""Seed database with OFFICIAL 2026 World Cup data (Beijing Time)."""
import json, sys, io
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except: pass

from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.models.database import init_db_sync, SyncSession
from app.models.team import Team
from app.models.match import Match, Group
from app.config import SEED_DIR

BJT = lambda m,d,h: datetime(2026, m, d, h, 0, 0)


def seed_teams(session):
    with open(SEED_DIR / "teams.json", "r", encoding="utf-8") as f:
        teams_data = json.load(f)
    team_map = {}
    for t in teams_data:
        team = Team(
            name_cn=t["name_cn"], name_en=t["name_en"],
            fifa_code=t["fifa_code"], fifa_ranking=t["fifa_ranking"],
            elo_rating=t["elo_rating"], elo_rating_initial=t["elo_rating"],
            is_host=t["is_host"], host_country=t["host_country"],
            confederation=t["confederation"],
            total_market_value=t["total_market_value"],
            avg_age=t["avg_age"], squad_size=26,
            home_advantage_bonus=(80 if t["is_host"] else 0),
        )
        session.add(team)
        team_map[t["fifa_code"]] = team
    session.flush()
    print(f"[OK] Seeded {len(teams_data)} teams")
    return team_map


def seed_groups(session, team_map):
    with open(SEED_DIR / "groups.json", "r", encoding="utf-8") as f:
        groups_data = json.load(f)
    for g in groups_data:
        team_ids = [team_map[code].id for code in g["teams"]]
        group = Group(name=g["name"], teams_json=json.dumps(team_ids))
        session.add(group)
        session.flush()
        for code in g["teams"]:
            team_map[code].group_id = group.id
    session.flush()
    print(f"[OK] Seeded {len(groups_data)} groups")


def generate_schedule(session, team_map):
    """Official 2026 World Cup schedule — ALL TIMES ARE BEIJING TIME (UTC+8)."""
    groups_data = {}
    with open(SEED_DIR / "groups.json", "r", encoding="utf-8") as f:
        for g in json.load(f):
            groups_data[g["name"]] = [team_map[c] for c in g["teams"]]

    # Venue data
    venues = {
        "Mexico City":    "阿兹台克体育场", "Guadalajara":  "阿克伦体育场",
        "Monterrey":      "BBVA体育场",      "Toronto":      "BMO球场",
        "Vancouver":      "BC广场",          "Los Angeles":  "SoFi体育场",
        "San Francisco":  "李维斯体育场",    "Seattle":      "流明球场",
        "Dallas":         "AT&T体育场",      "Houston":      "NRG体育场",
        "Kansas City":    "箭头体育场",      "Atlanta":      "梅赛德斯-奔驰体育场",
        "Miami":          "硬石体育场",      "Boston":       "吉列体育场",
        "Philadelphia":   "林肯金融球场",    "NY/NJ":        "大都会人寿体育场",
    }
    venue_altitudes = {
        "Mexico City": 2250, "Guadalajara": 1560, "Monterrey": 540,
        "Toronto": 76, "Vancouver": 2, "Los Angeles": 30, "San Francisco": 10,
        "Seattle": 50, "Dallas": 130, "Houston": 13, "Kansas City": 270,
        "Atlanta": 320, "Miami": 2, "Boston": 70, "Philadelphia": 12, "NY/NJ": 2,
    }

    matches = []

    # ===== GROUP STAGE (72 matches) =====
    # Format: (month, day, hour_bjt, group, home_idx, away_idx, matchday, city)
    # home_idx/away_idx: 0=seed1, 1=seed2, 2=seed3, 3=seed4

    GS = []  # group stage schedule tuples

    # Format: (month, day, hour_bjt, group, home_idx, away_idx, city)
    # home_idx/away_idx: 0=seed1(Pot1), 1=seed2(Pot2), 2=seed3(Pot3), 3=seed4(Pot4)

    # === MATCHDAY 1 (June 12-18) — VERIFIED from FIFA/zhibo8/hk01 ===
    md1 = [
        (6,12,3, "A",0,1, "Mexico City"),
        (6,12,10,"A",2,3, "Guadalajara"),
        (6,13,3, "B",0,1, "Toronto"),
        (6,13,9, "D",0,1, "Los Angeles"),
        (6,14,3, "B",2,3, "San Francisco"),
        (6,14,6, "C",0,1, "NY/NJ"),
        (6,14,9, "C",2,3, "Boston"),
        (6,14,12,"D",2,3, "Vancouver"),
        (6,15,1, "E",0,1, "Houston"),
        (6,15,4, "F",0,1, "Dallas"),
        (6,15,7, "E",2,3, "Philadelphia"),
        (6,15,10,"F",2,3, "Monterrey"),
        (6,16,0, "H",0,1, "Atlanta"),
        (6,16,3, "G",0,1, "Seattle"),
        (6,16,6, "H",2,3, "Miami"),
        (6,16,9, "G",2,3, "Los Angeles"),
        (6,17,3, "I",0,1, "NY/NJ"),
        (6,17,6, "I",2,3, "Boston"),
        (6,17,9, "J",0,1, "Kansas City"),
        (6,17,12,"J",2,3, "San Francisco"),
        (6,18,1, "K",0,1, "Houston"),
        (6,18,4, "L",0,1, "Dallas"),
        (6,18,7, "L",2,3, "Toronto"),
        (6,18,10,"K",2,3, "Mexico City"),
    ]
    for m,d,h,grp,hi,ai,city in md1:
        GS.append((m,d,h,grp,hi,ai,1,city))

    # === MATCHDAY 2 (June 19-24) — VERIFIED from FIFA/zhibo8/hk01 ===
    # MD2 pattern: team[0] vs team[2], team[3] vs team[2] varies by group
    md2 = [
        (6,19,0, "A",3,2, "Atlanta"),        # CZE vs RSA
        (6,19,3, "B",3,2, "Los Angeles"),    # SUI vs BIH
        (6,19,6, "B",0,2, "Vancouver"),      # CAN vs QAT
        (6,19,9, "A",0,2, "Guadalajara"),    # MEX vs KOR
        (6,20,3, "D",0,2, "Seattle"),        # USA vs AUS
        (6,20,6, "C",3,1, "Boston"),         # SCO vs MAR
        (6,20,8,"C",0,2, "Philadelphia"),    # BRA vs HAI  (time: 08:30)
        (6,20,11,"D",3,1, "San Francisco"),  # TUR vs PAR  (time: 11:00)
        (6,21,1, "F",0,2, "Houston"),        # NED vs SWE
        (6,21,4, "E",0,2, "Toronto"),        # GER vs CIV
        (6,21,8, "E",3,1, "Kansas City"),    # ECU vs CUW
        (6,21,12,"F",3,1, "Monterrey"),      # TUN vs JPN
        (6,22,0, "H",0,2, "Atlanta"),        # ESP vs KSA
        (6,22,3, "G",0,2, "Los Angeles"),    # BEL vs IRN
        (6,22,6, "H",3,1, "Miami"),          # URU vs CPV
        (6,22,9, "G",3,1, "Vancouver"),      # NZL vs EGY
        (6,23,1, "J",0,2, "Dallas"),         # ARG vs AUT
        (6,23,5, "I",0,2, "Philadelphia"),   # FRA vs IRQ
        (6,23,8, "I",3,1, "NY/NJ"),          # NOR vs SEN
        (6,23,11,"J",3,1, "San Francisco"),  # JOR vs ALG
        (6,24,1, "K",0,2, "Houston"),        # POR vs UZB
        (6,24,4, "L",0,2, "Boston"),         # ENG vs GHA
        (6,24,7, "L",3,1, "Toronto"),        # PAN vs CRO
        (6,24,10,"K",3,1, "Guadalajara"),    # COL vs COD
    ]
    for m,d,h,grp,hi,ai,city in md2:
        GS.append((m,d,h,grp,hi,ai,2,city))

    # === MATCHDAY 3 (June 25-28) — VERIFIED from FIFA/zhibo8/hk01 ===
    # Teams play simultaneously within groups
    md3 = [
        (6,25,3, "B",3,0, "Vancouver"),      (6,25,3, "B",1,2, "Seattle"),       # SUIvsCAN, BIHvsQAT
        (6,25,6, "C",3,0, "Miami"),          (6,25,6, "C",1,2, "Atlanta"),        # SCOvsBRA, MARvsHAI
        (6,25,9, "A",3,0, "Mexico City"),    (6,25,9, "A",2,1, "Monterrey"),      # CZEvsMEX, RSAvsKOR
        (6,26,4, "E",1,2, "Philadelphia"),   (6,26,4, "E",3,0, "NY/NJ"),          # CUWvsCIV, ECuvsGER
        (6,26,7, "F",2,1, "Dallas"),         (6,26,7, "F",3,0, "Kansas City"),    # JPNvsSWE, TUNvsNED
        (6,26,10,"D",3,0, "Los Angeles"),    (6,26,10,"D",1,2, "San Francisco"),  # TURvsUSA, PARvsAUS
        (6,27,3, "I",3,0, "Boston"),         (6,27,3, "I",1,2, "Toronto"),        # NORvsFRA, SENvsIRQ
        (6,27,8, "H",1,2, "Houston"),        (6,27,8, "H",3,0, "Guadalajara"),    # CPVvsKSA, URUvsESP
        (6,27,11,"G",2,1, "Seattle"),        (6,27,11,"G",3,0, "Vancouver"),      # EGYvsIRN, NZLvsBEL
        (6,28,5, "L",3,0, "NY/NJ"),          (6,28,5, "L",1,2, "Philadelphia"),   # PANvsENG, CROvsGHA
        (6,28,7,"K",3,0, "Miami"),           (6,28,7, "K",1,2, "Atlanta"),        # COLvsPOR, CODvsUZB (time: 07:30)
        (6,28,10,"J",2,1, "Kansas City"),    (6,28,10,"J",3,0, "Dallas"),         # ALGvsAUT, JORvsARG
    ]
    for m,d,h,grp,hi,ai,city in md3:
        GS.append((m,d,h,grp,hi,ai,3,city))

    # Create all group stage matches
    for m,d,h,grp,hi,ai,md,city in GS:
        teams = groups_data[grp]
        venue_name = venues.get(city, city)
        alt = venue_altitudes.get(city, 0)
        m_obj = Match(
            match_date=BJT(m,d,h),
            stage="小组赛", matchday=md,
            home_team_id=teams[hi].id, away_team_id=teams[ai].id,
            status="scheduled", venue=venue_name, city=city, altitude=alt,
        )
        session.add(m_obj)
        matches.append(m_obj)

    session.flush()

    # ===== KNOCKOUT STAGE (32 matches) — VERIFIED =====
    ph = list(team_map.values())
    ko = [
        # 1/16决赛 (June 29-July 4): 16 matches
        (6,29,3,"1/16决赛","Los Angeles"),(6,30,1,"1/16决赛","Houston"),
        (6,30,4,"1/16决赛","Boston"),(6,30,9,"1/16决赛","Monterrey"),
        (7,1,1,"1/16决赛","NY/NJ"),(7,1,5,"1/16决赛","Dallas"),
        (7,1,9,"1/16决赛","Mexico City"),(7,2,0,"1/16决赛","Los Angeles"),
        (7,2,4,"1/16决赛","Vancouver"),(7,2,8,"1/16决赛","Atlanta"),
        (7,3,3,"1/16决赛","Seattle"),(7,3,7,"1/16决赛","San Francisco"),
        (7,3,11,"1/16决赛","Toronto"),(7,4,2,"1/16决赛","Miami"),
        (7,4,6,"1/16决赛","Kansas City"),(7,4,9,"1/16决赛","Philadelphia"),
        # 1/8决赛 (July 5-8): 8 matches
        (7,5,1,"1/8决赛","Philadelphia"),(7,5,5,"1/8决赛","Houston"),
        (7,6,4,"1/8决赛","NY/NJ"),(7,6,8,"1/8决赛","Mexico City"),
        (7,7,3,"1/8决赛","Dallas"),(7,7,8,"1/8决赛","Seattle"),
        (7,8,0,"1/8决赛","Atlanta"),(7,8,4,"1/8决赛","Vancouver"),
        # 1/4决赛 (July 9-12): 4 matches
        (7,10,4,"1/4决赛","Boston"),(7,11,3,"1/4决赛","Los Angeles"),
        (7,12,5,"1/4决赛","Miami"),(7,12,9,"1/4决赛","Kansas City"),
        # 半决赛 (July 15-16): 2 matches
        (7,15,3,"半决赛","Dallas"),(7,16,3,"半决赛","Atlanta"),
        # 季军赛 + 决赛
        (7,19,5,"季军赛","Miami"),(7,20,3,"决赛","NY/NJ"),
    ]
    for m,d,h,stage,city in ko:
        venue_name = venues.get(city, city)
        alt = venue_altitudes.get(city, 0)
        m_obj = Match(
            match_date=BJT(m,d,h), stage=stage, matchday=0,
            home_team_id=ph[0].id, away_team_id=ph[1].id,
            status="scheduled", venue=venue_name, city=city, altitude=alt,
        )
        session.add(m_obj)
        matches.append(m_obj)

    session.flush()
    print(f"[OK] Generated {len(matches)} matches ({len(GS)} group + {len(ko)} knockout = {len(GS)+len(ko)})")

    # Print today's matches (June 12 BJT)
    today = datetime(2026, 6, 12).date()
    today_ms = [m for m in matches if m.match_date.date() == today]
    print(f"\n  >>> Today (June 12, Beijing Time):")
    for m in sorted(today_ms, key=lambda x: x.match_date):
        h = session.get(Team, m.home_team_id)
        a = session.get(Team, m.away_team_id)
        print(f"    {m.match_date.strftime('%m/%d %H:%M')} BJT  {h.name_cn} vs {a.name_cn}  [{m.stage} {m.city}]")


if __name__ == "__main__":
    print("Seeding 2026 World Cup (Official Data, Beijing Time)...")
    init_db_sync()
    session = SyncSession()
    try:
        team_map = seed_teams(session)
        seed_groups(session, team_map)
        generate_schedule(session, team_map)
        session.commit()
        print("\n[OK] Database seeded successfully!")
    except Exception as e:
        session.rollback()
        import traceback; traceback.print_exc()
        raise
    finally:
        session.close()
