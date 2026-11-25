#!/usr/bin/env python3
"""Pull the USCCS fall regular season from SportsEngine's public season-microsite feed
(the same feed collegeclubsoccer.com's Schedules & Standings pages use; no login needed).

Writes data/data.json (games, teams, divisions, standings), data/players.json (player stats)
and adds any new team logos to data/logos.json. Files are only rewritten when the content
actually changed, so an unchanged season makes no commit and no Netlify deploy.
"""
import io, json, pathlib, sys, time, base64, datetime, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

SEASONS = [("men", "6a0c976961444a4e0cf2ef71"), ("women", "6a0c979a98c2fde79e7c20cc")]
API = "https://se-api.sportsengine.com/v3/microsites/"
DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
STATS_SHEET = "https://docs.google.com/spreadsheets/d/1W42UPt2QqSjsULjShssKw0vwEBdkp1s4g19iKlZhcEQ/export?format=csv&gid=0"   # RAWresponses tab, "anyone with the link can view"
UA = {"User-Agent": "USCCS-season-page/1.0 (+https://2026-usccs-fall-season.netlify.app)", "Accept": "application/json"}


def get(url, as_json=True, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                body = r.read()
                return json.loads(body) if as_json else body
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if i == tries - 1:
                raise RuntimeError(f"{url}: {e}")
            time.sleep(2 * (i + 1))


def api(path): return get(API + path)


def pages(base, per):
    first = api(f"{base}&page=1&per_page={per}")
    out = list(first["result"])
    for p in range(2, first["metadata"]["pagination"]["totalPages"] + 1):
        out += api(f"{base}&page={p}&per_page={per}")["result"]
    return out


def team_players(prog, team_id):
    # one team per request: SportsEngine's stats paging is unstable across big result sets
    out, p = [], 1
    while True:
        r = api(f"season_player_stats?program_id={prog}&compact=true&stat_module=soccer_individual&team_ids={team_id}&page={p}&per_page=100")
        out += r["result"]
        pg = r["metadata"]["pagination"]
        if pg.get("lastPage") or p >= pg.get("totalPages", 1):
            return out
        p += 1


def pull(key, prog):
    season = api(f"seasons/{prog}")["result"]
    divs = [[d["id"], d["name"]] for d in api(f"divisions?program_id={prog}")["result"]]
    events = pages(f"events?program_id={prog}&order_by=starts_at&direction=asc", 200)
    teams, by_name, season_team_ids, games = {}, {}, [], []
    for e in events:
        if e.get("event_type") != "game":
            continue
        x = (e.get("source") or {}).get("extended_attributes") or {}
        div = ""
        for pr in e.get("principals") or []:
            if pr.get("type") != "team":
                continue
            a = pr.get("extended_attributes") or {}
            if a.get("outside_team"):
                continue
            teams[pr["id"]] = [a.get("name", ""), a.get("division_id") or pr.get("division_id"), (a.get("logos") or {}).get("large_square", "")]
            by_name[a.get("name", "")] = pr["id"]
            if a.get("team_id") and a["team_id"] not in season_team_ids:
                season_team_ids.append(a["team_id"])
            div = a.get("division_id") or div
        hs, as_ = x.get("home_team_score"), x.get("away_team_score")
        games.append([e["start_date_time"], e["local_timezone"], e["status"], x.get("home_team_id") or "", x.get("away_team_id") or "",
                      "" if hs is None else hs, "" if as_ is None else as_,
                      " · ".join(v for v in (e.get("location_description"), e.get("location_name")) if v), div, 1 if e.get("tbd_time") else 0])
    standings = []
    for n in api(f"standings?program_id={prog}")["result"]:
        rows = []
        for t in n.get("teamRecords") or []:
            v = t.get("values") or {}
            rows.append([t["team_name"], v.get("games"), v.get("w"), v.get("l"), v.get("t"), v.get("pf"), v.get("pa"), v.get("pd"), v.get("st_pts"), v.get("ycards"), v.get("rcards")])
        tid = by_name.get(rows[0][0]) if rows else None
        standings.append({"div": (teams.get(tid) or [None, None])[1] or n.get("flight_id"), "rows": rows})
    with ThreadPoolExecutor(8) as ex:
        per_team = list(ex.map(lambda t: team_players(prog, t), season_team_ids))
    seen, players, roster = set(), [], []
    for lst in per_team:
        for r in lst:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            v = (r.get("values") or {}).get("soccer_individual") or {}
            n = lambda k: int(float(v.get(k) or 0))
            row = [f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip(), r.get("team_name", ""), n("soigp"), n("soig"), n("soia"), n("soiyc"), n("soirc")]
            if row[3] or row[4] or row[5] or row[6]:
                players.append(row)
            if row[0]:   # every player on a season roster (SportsEngine keeps a stats line for each)
                roster.append([row[0], row[1], str(r.get("jersey_number") or ""), row[2]])
    players.sort(key=lambda r: (r[1], r[0], r[2:]))
    roster.sort(key=lambda r: (r[1], r[0], r[2], r[3]))
    print(f"{key}: {len(divs)} divisions, {len(teams)} teams, {len(games)} games, {len(players)} players with stats, {len(roster)} rostered", flush=True)
    return {"key": key, "name": season["name"], "start": season["start_date"], "end": season["end_date"],
            "divs": divs, "teams": teams, "games": games, "standings": standings}, players, roster


def update_logos(seasons):
    path = DATA / "logos.json"
    logos = json.loads(path.read_text()) if path.exists() else {}
    want = sorted({t[2] for s in seasons for t in s["teams"].values() if t[2]} - logos.keys())
    if not want:
        return False
    from PIL import Image
    for url in want:
        try:
            im = Image.open(io.BytesIO(get(url, as_json=False))).convert("RGBA")
            im.thumbnail((64, 64))
            canvas = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            canvas.paste(im, ((64 - im.width) // 2, (64 - im.height) // 2))
            buf = io.BytesIO(); canvas.save(buf, "WEBP", quality=85)
            logos[url] = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
            print("new logo", url, flush=True)
        except Exception as e:
            print("logo failed", url, e, flush=True)
    path.write_text(json.dumps(logos, separators=(",", ":")))
    return True


def main():
    seasons, players, rosters = [], {}, {}
    for key, prog in SEASONS:
        s, p, ro = pull(key, prog)
        seasons.append(s); players[key] = p; rosters[key] = ro
    if sum(len(s["games"]) for s in seasons) == 0:
        sys.exit("No games returned; keeping the existing data.")
    changed = update_logos(seasons)
    dpath, ppath = DATA / "data.json", DATA / "players.json"
    old = json.loads(dpath.read_text()) if dpath.exists() else {}
    if old.get("seasons") != json.loads(json.dumps(seasons)):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        dpath.write_text(json.dumps({"pulled": stamp, "seasons": seasons}, separators=(",", ":")))
        changed = True
    oldp = json.loads(ppath.read_text()) if ppath.exists() else {}
    if {k: sorted(map(tuple, v)) for k, v in oldp.items()} != {k: sorted(map(tuple, v)) for k, v in players.items()}:
        ppath.write_text(json.dumps(players, separators=(",", ":")))
        if old.get("seasons") == json.loads(json.dumps(seasons)):   # stats-only change still bumps "last change"
            d = json.loads(dpath.read_text()); d["pulled"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            dpath.write_text(json.dumps(d, separators=(",", ":")))
        changed = True
    rpath = DATA / "rosters.json"
    new_r = json.dumps(rosters, separators=(",", ":"))
    if sum(len(v) for v in rosters.values()) and (not rpath.exists() or rpath.read_text() != new_r):
        rpath.write_text(new_r); changed = True
        print("rosters updated", flush=True)
    # USCCS stat sheet (goals, assists, clean sheets, self-reported cards)
    try:
        sheet = get(STATS_SHEET, as_json=False).decode("utf-8-sig").replace("\r\n", "\n")   # normalize line endings so unchanged sheets compare equal
        spath = DATA / "sheet_stats.csv"
        if "game uid" in sheet.split("\n", 1)[0].lower():
            if not spath.exists() or spath.read_text(encoding="utf-8") != sheet:
                spath.write_text(sheet, encoding="utf-8")
                d = json.loads(dpath.read_text()); d["pulled"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                dpath.write_text(json.dumps(d, separators=(",", ":")))
                changed = True
                print("stat sheet updated", flush=True)
        else:
            print("stat sheet download didn't look like the stats tab; keeping the previous copy", flush=True)
    except Exception as e:
        print("stat sheet not reachable, keeping the previous copy:", e, flush=True)
    print("CHANGED" if changed else "NO CHANGE")


if __name__ == "__main__":
    main()
