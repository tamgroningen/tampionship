"""KNLTB match scraper for TAMpionship.
Scrapes all TAM team matches from KNLTB voorjaar Tennis 2026.
Also fetches per-match ratings for all players.
Pure requests + BeautifulSoup, no Selenium needed.
"""
import time, json, os, re
import requests
from bs4 import BeautifulSoup

BASE = "https://mijnknltb.toernooi.nl"
LEAGUE_ID = "4F146D7E-2C0C-45ED-BD0D-C1707F7C820F"
SEASON_ID = "5a8eec57-21ad-45d2-aba7-e2ee142cce81"
PREV_SEASON_ID = "4dcf0a0d-611a-4df0-8e14-7338c40ecbc6"  # 24/25
RATING_CODE = "55d9ce5f-ff55-4f1f-99dc-bc1469c41544"

# Players who play for TAM but whose home club is elsewhere.
# search_player_uuid prefers the TAM-club match, so for these players it would
# otherwise fall back to the first unrelated result. Add name -> UUID here to
# pin the correct player.
PLAYER_UUID_OVERRIDES = {
    "Sven van Dijk": "D6FE4FDA-BBF7-4328-A4D7-27F2B0203762",  # L.T.C. Aloe
}

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
    team_name = ""
    team_link = soup.select_one(f'a[href*="/team/{team_id}"]')
    if team_link:
        team_name = team_link.get_text(strip=True)
    draw_link = soup.select_one('a[href*="/draw/"]')
    category = draw_link.get_text(strip=True) if draw_link else ""
    match_urls = []
    for link in soup.select('a[href*="/team-match/"]'):
        href = link["href"]
        text = link.get_text(separator=" ", strip=True)
        has_score = any(c.isdigit() for c in text) and "-" in text
        if has_score and href not in [m["href"] for m in match_urls]:
            date = ""
            date_match = re.search(r'(\d{1,2}-\d{1,2}-\d{4})', text)
            if date_match:
                date = date_match.group(1)
            round_match = re.search(r'(Ronde \d+)', text)
            round_name = round_match.group(1) if round_match else ""
            match_urls.append({"href": href, "date": date, "round": round_name})
    return {"team_name": team_name, "category": category, "match_urls": match_urls}


def parse_team_match(session, path):
    """Parse a team-match page for team result and individual partijen."""
    resp = session.get(f"{BASE}{path}", timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    team_links = soup.select('a[href*="/team/"]')
    teams = []
    for tl in team_links:
        n = tl.get_text(strip=True)
        if n and n not in teams:
            teams.append(n)
    round_info, league_info = "", ""
    hero = soup.select_one(".card--dark")
    if hero:
        for line in hero.get_text(separator="\n", strip=True).split("\n"):
            line = line.strip()
            if "ronde" in line.lower():
                round_info = line
            if "klasse" in line.lower() or "zondag" in line.lower() or "zaterdag" in line.lower():
                league_info = line
    score_el = soup.select_one(".score")
    team_score = score_el.get_text(strip=True).replace("\n", "").replace(" ", "") if score_el else ""
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
        scores = [s.get_text(strip=True) for s in item.select(".points__cell")]
        sets = []
        for i in range(0, len(scores), 2):
            if i + 1 < len(scores):
                try:
                    sets.append([int(scores[i]), int(scores[i + 1])])
                except ValueError:
                    sets.append([scores[i], scores[i + 1]])
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


# ------------------------------------------------------------------
# Rating scraping
# ------------------------------------------------------------------
def search_player_uuid(session, name):
    """Search for a player and return UUID, preferring TAM members.

    For players with an explicit override (e.g. TAM players registered at
    another home club), return the pinned UUID without searching.
    """
    if name in PLAYER_UUID_OVERRIDES:
        return PLAYER_UUID_OVERRIDES[name]
    resp = session.get(f"{BASE}/find/player/DoSearch", params={"Page": 1, "SportID": 0, "Query": name},
                       headers={"X-Requested-With": "XMLHttpRequest"}, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for media in soup.select("div.media"):
        link = media.select_one('a.media__link[href*="/player-profile/"]')
        if not link:
            continue
        uuid = link["href"].split("/player-profile/")[1].strip("/")
        club_el = media.select_one(".media__subheading .nav-link__value")
        club = club_el.get_text(strip=True) if club_el else ""
        results.append({"uuid": uuid, "club": club})
    tam = next((r for r in results if "tam" in r["club"].lower()), None)
    if tam:
        return tam["uuid"]
    # No TAM-club hit: refuse to guess. Returning a random first result silently
    # pollutes rating data with the wrong person's history.
    if results:
        print(f"WARN: no TAM club match for {name!r}; add to PLAYER_UUID_OVERRIDES if needed", flush=True)
    return None


def fetch_rating_matches(session, player_uuid, ranktype):
    """Fetch rating match list for a player. ranktype=1 singles, 2 doubles."""
    url = f"{BASE}/player-profile/{player_uuid}/rating/{SEASON_ID}/RatingMatchList"
    params = {"RatingCode": RATING_CODE, "ranktype": ranktype}
    resp = session.get(url, params=params, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=15)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    matches = []
    for item in soup.select('.match-group__item'):
        headers = [h.get_text(strip=True) for h in item.select('.match__header-title-item')]
        match_type = headers[-1] if headers else ""
        round_name = ""
        for h in headers:
            if h.startswith("Ronde"):
                round_name = h
        rows = item.select('.match__row')
        players_data = []
        for row in rows:
            name_el = row.select_one('.match__row-title-value-content')
            raw_name = name_el.get_text(strip=True) if name_el else ''
            rating_match = re.search(r'\((\d+[,.]\d+)\)', raw_name)
            rating = float(rating_match.group(1).replace(',', '.')) if rating_match else None
            clean_name = re.sub(r'\s*\([\d,.]+\)', '', raw_name).strip()
            won = bool(row.select_one('.tag--success'))
            # For doubles, get partner name too
            all_names = [p.get_text(strip=True) for p in row.select('.match__row-title-value-content')]
            clean_names = [re.sub(r'\s*\([\d,.]+\)', '', n).strip() for n in all_names]
            ratings = []
            for n in all_names:
                rm = re.search(r'\((\d+[,.]\d+)\)', n)
                ratings.append(float(rm.group(1).replace(',', '.')) if rm else None)
            players_data.append({"names": clean_names, "ratings": ratings, "won": won})
        matches.append({"type": match_type, "round": round_name, "sides": players_data})
    return matches


def fetch_rating_history(session, player_uuid, player_name, ranktype, season_id):
    """Fetch rating match list with dates for a player in a given season."""
    url = f"{BASE}/player-profile/{player_uuid}/rating/{season_id}/RatingMatchList"
    params = {"RatingCode": RATING_CODE, "ranktype": ranktype}
    resp = session.get(url, params=params, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=15)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    points = []
    for item in soup.select('.match-group__item'):
        # Parse date
        date_elem = item.select_one(".match__footer .icon-clock + .nav-link__value")
        if not date_elem:
            continue
        date_text = date_elem.get_text(strip=True)
        parts = date_text.split(" ", 1)
        date_str = parts[1] if len(parts) == 2 else parts[0]

        # Parse player rating and win/loss
        rows = item.select('.match__row')
        for row in rows:
            all_names = [p.get_text(strip=True) for p in row.select('.match__row-title-value-content')]
            clean_names = [re.sub(r'\s*\([\d,.]+\)', '', n).strip() for n in all_names]
            if player_name not in clean_names:
                continue
            idx = clean_names.index(player_name)
            rm = re.search(r'\((\d+[,.]\d+)\)', all_names[idx])
            if not rm:
                continue
            rating = float(rm.group(1).replace(',', '.'))
            won = bool(row.select_one('.tag--success'))
            points.append({"date": date_str, "rating": rating, "won": won})
            break
    return points


def build_rating_history(session, all_matches):
    """Build 52-week rating history for all TAM players."""
    # Collect unique TAM player names
    tam_players = set()
    for match in all_matches:
        for partij in match["partijen"]:
            for side_key in ["home", "away"]:
                side = partij.get(side_key, {})
                if side.get("team", "").startswith("TAM"):
                    for pname in side.get("players", []):
                        tam_players.add(pname)

    print(f"\nFetching rating history for {len(tam_players)} TAM players...")
    history = {}

    for i, name in enumerate(sorted(tam_players)):
        print(f"  [{i+1}/{len(tam_players)}] {name}...", end=" ", flush=True)
        try:
            uuid = search_player_uuid(session, name)
            if not uuid:
                print("not found")
                continue

            player_history = {"singles": [], "doubles": []}
            for ranktype, key in [(1, "singles"), (2, "doubles")]:
                for sid in [SEASON_ID, PREV_SEASON_ID]:
                    pts = fetch_rating_history(session, uuid, name, ranktype, sid)
                    player_history[key].extend(pts)
                    time.sleep(0.1)
            # Deduplicate and sort by date
            def _date_key(p):
                d, m, y = p["date"].split("-")
                return (int(y), int(m), int(d))
            for key in ["singles", "doubles"]:
                seen = set()
                deduped = []
                for p in player_history[key]:
                    k = (p["date"], p["rating"])
                    if k not in seen:
                        seen.add(k)
                        deduped.append(p)
                deduped.sort(key=_date_key)
                player_history[key] = deduped

            total = len(player_history["singles"]) + len(player_history["doubles"])
            if total > 0:
                history[name] = player_history
            print(f"{len(player_history['singles'])}S {len(player_history['doubles'])}D")
        except Exception as e:
            print(f"error: {e}")
        time.sleep(0.15)

    return history


def build_rating_lookup(session, all_matches):
    """Build a rating lookup for all TAM players.

    Only TAM players are queried directly. Opponent ratings are captured as
    a side effect: fetch_rating_matches returns both sides of each match, and
    the opponent-storing branch below keys them by (match_type, round). So
    opponents get full coverage without us needing to search for their UUIDs.
    """
    all_player_names = set()
    for match in all_matches:
        for partij in match["partijen"]:
            for side_key in ["home", "away"]:
                side = partij.get(side_key, {})
                if side.get("team", "").startswith("TAM"):
                    for pname in side.get("players", []):
                        all_player_names.add(pname)

    print(f"\nFetching ratings for {len(all_player_names)} TAM players...")

    # player_name -> {(match_type, round) -> rating}
    rating_lookup = {}

    for i, name in enumerate(sorted(all_player_names)):
        print(f"  [{i+1}/{len(all_player_names)}] {name}...", end=" ", flush=True)
        try:
            uuid = search_player_uuid(session, name)
            if not uuid:
                print("not found")
                continue

            for ranktype, label in [(1, "S"), (2, "D")]:
                rm = fetch_rating_matches(session, uuid, ranktype)
                for m in rm:
                    for side in m["sides"]:
                        for j, pname in enumerate(side["names"]):
                            if pname == name and j < len(side["ratings"]) and side["ratings"][j]:
                                key = (m["type"], m["round"])
                                if name not in rating_lookup:
                                    rating_lookup[name] = {}
                                rating_lookup[name][f"{m['type']}|{m['round']}"] = side["ratings"][j]
                            # Also store opponent ratings
                        for j, pname in enumerate(side["names"]):
                            if j < len(side["ratings"]) and side["ratings"][j]:
                                if pname not in rating_lookup:
                                    rating_lookup[pname] = {}
                                rating_lookup[pname][f"{m['type']}|{m['round']}"] = side["ratings"][j]

                time.sleep(0.1)
            print(f"{len(rating_lookup.get(name, {}))} ratings")
        except Exception as e:
            print(f"error: {e}")
        time.sleep(0.15)

    return rating_lookup


def enrich_matches_with_ratings(all_matches, rating_lookup):
    """Add rating data to each partij in each match."""
    for match in all_matches:
        round_name = match.get("round", "")
        for partij in match["partijen"]:
            mtype = partij["type"]
            key_suffix = f"{mtype}|{round_name}"
            for side_key in ["home", "away"]:
                side = partij.get(side_key, {})
                ratings = []
                for pname in side.get("players", []):
                    r = rating_lookup.get(pname, {}).get(key_suffix)
                    ratings.append(r)
                side["ratings"] = ratings


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
    all_match_urls = {}
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

    # Step 4: Fetch ratings and enrich matches
    t = time.time()
    rating_lookup = build_rating_lookup(session, all_matches)
    enrich_matches_with_ratings(all_matches, rating_lookup)
    print(f"Ratings enriched ({time.time()-t:.1f}s)")

    # Step 5: Fetch 52-week rating history for TAM players
    t = time.time()
    rating_history = build_rating_history(session, all_matches)
    print(f"Rating history fetched ({time.time()-t:.1f}s)")

    # Save
    out_path = os.path.join(script_dir, "knltb_matches.json")
    with open(out_path, "w") as f:
        json.dump(all_matches, f, indent=2, ensure_ascii=False)

    # Also save rating lookup for reference
    rating_path = os.path.join(script_dir, "player_ratings.json")
    serializable = {name: ratings for name, ratings in rating_lookup.items()}
    with open(rating_path, "w") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)

    # Save rating history
    history_path = os.path.join(script_dir, "rating_history.json")
    with open(history_path, "w") as f:
        json.dump(rating_history, f, indent=2, ensure_ascii=False)

    total_partijen = sum(len(m["partijen"]) for m in all_matches)
    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"Total time: {elapsed:.1f}s")
    print(f"TAM teams: {len(TAM_TEAM_IDS)}")
    print(f"Team matches: {len(all_matches)}")
    print(f"Total partijen: {total_partijen}")
    print(f"Players with ratings: {len(rating_lookup)}")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
