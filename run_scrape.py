"""KNLTB match scraper for TAMpionship.
Scrapes all TAM team matches from KNLTB voorjaar Tennis 2026.
Pure requests + BeautifulSoup, no Selenium needed.
"""
import time, json, os
import requests
from bs4 import BeautifulSoup

BASE = "https://mijnknltb.toernooi.nl"
LEAGUE_ID = "4F146D7E-2C0C-45ED-BD0D-C1707F7C820F"

# All 23 TAM teams from the club page
TAM_TEAM_IDS = [
    6923, 7026, 5750, 6135, 6749,         # Heren Zaterdag
    12468, 14563,                           # Heren Zondag
    11586, 11605,                           # Dames Zondag
    10979, 11191, 11180, 11436, 11349, 11425,  # Gemengd Zaterdag
    16391, 16415, 16467, 16469, 16468, 16470, 16522, 16585,  # Gemengd Zondag
]


def login(username, password):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
    resp = session.get(f"{BASE}/user/login", timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    cf = soup.select_one('form[action*="cookiewall"]')
    if cf:
        data = {i.get("name"): i.get("value", "") for i in cf.select("input") if i.get("name")}
        session.post(f"{BASE}/cookiewall/Save", data=data, timeout=15, allow_redirects=True)
    resp = session.get(f"{BASE}/user/login", timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    token = soup.select_one('input[name="__RequestVerificationToken"]')["value"]
    session.post(f"{BASE}/user/login", data={
        "Login": username, "Password": password, "__RequestVerificationToken": token
    }, timeout=15, allow_redirects=True)
    return session


def get_team_info_and_matches(session, team_id):
    """Get team name, league category, and all played team-match URLs."""
    resp = session.get(f"{BASE}/league/{LEAGUE_ID}/team/{team_id}", timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Team name from heading
    team_name = ""
    team_link = soup.select_one(f'a[href*="/team/{team_id}"]')
    if team_link:
        team_name = team_link.get_text(strip=True)

    # League category from draw link
    draw_link = soup.select_one('a[href*="/draw/"]')
    category = draw_link.get_text(strip=True) if draw_link else ""

    # All team-match URLs with dates
    match_urls = []
    for link in soup.select('a[href*="/team-match/"]'):
        href = link["href"]
        text = link.get_text(separator=" ", strip=True)
        has_score = any(c.isdigit() for c in text) and "-" in text
        if has_score and href not in [m["href"] for m in match_urls]:
            # Extract date from text like "Ronde 1 • ma 6-4-2026 W TAM 1 6 - 0 ..."
            date = ""
            import re as _re
            date_match = _re.search(r'(\d{1,2}-\d{1,2}-\d{4})', text)
            if date_match:
                date = date_match.group(1)
            round_match = _re.search(r'(Ronde \d+)', text)
            round_name = round_match.group(1) if round_match else ""
            match_urls.append({"href": href, "date": date, "round": round_name})

    return {"team_name": team_name, "category": category, "match_urls": match_urls}


def parse_team_match(session, path):
    """Parse a team-match page for team result and individual partijen."""
    resp = session.get(f"{BASE}{path}", timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Team names
    team_links = soup.select('a[href*="/team/"]')
    teams = []
    for tl in team_links:
        n = tl.get_text(strip=True)
        if n and n not in teams:
            teams.append(n)

    # Round/league from header
    round_info, league_info = "", ""
    hero = soup.select_one(".card--dark")
    if hero:
        for line in hero.get_text(separator="\n", strip=True).split("\n"):
            line = line.strip()
            if "ronde" in line.lower():
                round_info = line
            if "klasse" in line.lower() or "zondag" in line.lower() or "zaterdag" in line.lower():
                league_info = line

    # Overall team score
    score_el = soup.select_one(".score")
    team_score = score_el.get_text(strip=True).replace("\n", "").replace(" ", "") if score_el else ""

    # Individual partijen
    partijen = []
    for item in soup.select(".match-group__item"):
        mtype_el = item.select_one(".match__header-title-item")
        mtype = mtype_el.get_text(strip=True) if mtype_el else ""

        rows = item.select(".match__row")
        team_data = []
        for row in rows:
            th = row.select_one(".match__row-title-header")
            team_data.append({
                "team": th.get_text(strip=True) if th else "",
                "players": [p.get_text(strip=True) for p in row.select(".match__row-title-value-content")],
                "won": bool(row.select_one(".tag--success")),
            })

        # Set scores as pairs [home, away]
        scores = [s.get_text(strip=True) for s in item.select(".points__cell")]
        sets = []
        for i in range(0, len(scores), 2):
            if i + 1 < len(scores):
                try:
                    sets.append([int(scores[i]), int(scores[i + 1])])
                except ValueError:
                    sets.append([scores[i], scores[i + 1]])

        # Format set scores as string like "6-4 3-6 7-5"
        set_scores_str = " ".join(f"{s[0]}-{s[1]}" for s in sets)

        partijen.append({
            "type": mtype,
            "home": {"team": team_data[0]["team"], "players": team_data[0]["players"], "won": team_data[0]["won"]} if team_data else {},
            "away": {"team": team_data[1]["team"], "players": team_data[1]["players"], "won": team_data[1]["won"]} if len(team_data) > 1 else {},
            "sets": sets,
            "set_scores": set_scores_str,
        })

    return {
        "home_team": teams[0] if teams else "",
        "away_team": teams[1] if len(teams) > 1 else "",
        "team_score": team_score,
        "round": round_info,
        "league": league_info,
        "partijen": partijen,
    }


def main():
    start_time = time.time()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Step 1: Login
    t = time.time()
    print("Logging in...", end=" ", flush=True)
    username = os.environ.get("KNLTB_USERNAME")
    password = os.environ.get("KNLTB_PASSWORD")
    if not username or not password:
        raise RuntimeError("Set KNLTB_USERNAME and KNLTB_PASSWORD environment variables")
    session = login(username, password)
    print(f"done ({time.time()-t:.1f}s)")

    # Step 2: Get all team match URLs from all 23 TAM teams
    t = time.time()
    print(f"Fetching {len(TAM_TEAM_IDS)} TAM team pages...", flush=True)
    all_match_urls = {}  # href -> {team_name, date, round}
    team_info_list = []
    for team_id in TAM_TEAM_IDS:
        info = get_team_info_and_matches(session, team_id)
        team_info_list.append(info)
        for mu in info["match_urls"]:
            if mu["href"] not in all_match_urls:
                all_match_urls[mu["href"]] = {"team_name": info["team_name"], "date": mu["date"], "round": mu["round"]}
        print(f"  {info['team_name']}: {len(info['match_urls'])} played matches ({info['category'][:50]})")
        time.sleep(0.15)
    print(f"Found {len(all_match_urls)} unique played matches ({time.time()-t:.1f}s)")

    # Step 3: Parse each team-match page
    t = time.time()
    print(f"\nParsing {len(all_match_urls)} team matches...")
    all_matches = []
    for i, (href, meta) in enumerate(all_match_urls.items()):
        print(f"  [{i+1}/{len(all_match_urls)}]", end=" ", flush=True)
        match = parse_team_match(session, href)
        match["tam_team"] = meta["team_name"]
        match["date"] = meta["date"]
        match["round"] = meta["round"]
        all_matches.append(match)
        n_p = len(match["partijen"])
        print(f"{match['home_team']} vs {match['away_team']} ({match['team_score']}) - {n_p} partijen")
        time.sleep(0.15)
    print(f"Done parsing ({time.time()-t:.1f}s)")

    # Save
    out_path = os.path.join(script_dir, "knltb_matches.json")
    with open(out_path, "w") as f:
        json.dump(all_matches, f, indent=2, ensure_ascii=False)

    total_partijen = sum(len(m["partijen"]) for m in all_matches)
    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"Total time: {elapsed:.1f}s")
    print(f"TAM teams: {len(TAM_TEAM_IDS)}")
    print(f"Team matches: {len(all_matches)}")
    print(f"Total partijen: {total_partijen}")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
