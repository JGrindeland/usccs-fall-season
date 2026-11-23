"""Merge USCCS's own stat reports into the SportsEngine season data.

Sources
  data/sheet_stats.csv  live Google sheet (RAWresponses tab): goals, assists, clean sheets,
                        plus self-reported cards. One row per event, reported per team per game.
  data/cards.csv        misconduct-review export: yellow and red cards (the official card record).

Rules (agreed with Jordan, Nov 23 2026)
  * Each report is matched to a SportsEngine game by gender + local date + team (+ opponent, + kickoff time
    for double-headers; a date 1-2 days off is accepted when nothing matches on the day).
  * A team that submitted more than once for a game: per player and event type, the highest count from any
    one submission is used (repeat submissions are not added together).
  * Cards: the misconduct CSV is the record. A self-reported card from the sheet is used only when the CSV has
    no card of the same type for that player in that game (it would be a duplicate otherwise).
  * Season totals never double count SportsEngine: per player, each stat is the higher of SportsEngine's season
    total and the total from these reports.
Anything that can't be matched, or a team-game whose reported goals exceed its score, goes to data/review.md.
"""
import csv, io, re, datetime, collections
from zoneinfo import ZoneInfo

norm = lambda n: re.sub(r"[^a-z0-9]", "", (n or "").lower())
NATIONALS = (datetime.date(2026, 11, 11), datetime.date(2026, 11, 15))
YELLOW_REASONS = {"unsporting behavior", "dissent", "delaying the restart", "persistent offense",
                  "entering/leaving field of play", "failure to respect distance"}


def pdate(s):
    s = (s or "").strip().split(" ")[0]
    m = re.match(r"(\d+)[/.-](\d+)[/.-](\d{4})", s)
    if not m:
        m2 = re.match(r"(\d{4})-(\d+)-(\d+)", s)
        return datetime.date(int(m2[1]), int(m2[2]), int(m2[3])) if m2 else None
    a, b, y = int(m[1]), int(m[2]), int(m[3])
    orders = ((b, a),) if "." in s else ((a, b), (b, a))      # dotted dates are day-first; otherwise month-first unless impossible
    for mo, da in orders:
        try:
            d = datetime.date(y, mo, da)
        except ValueError:
            continue
        if datetime.date(2026, 8, 1) <= d <= datetime.date(2026, 11, 30):   # fall season window
            return d
    return None


def ptime(s):
    m = re.match(r"\s*(\d+):(\d+)(?::\d+)?\s*([AaPp][Mm])?", s or "")
    if not m:
        return None
    h, mi = int(m[1]), int(m[2])
    if m[3]:
        h = h % 12 + (12 if m[3].lower() == "pm" else 0)
    return h * 60 + mi


class GameIndex:
    """(gender, local date, team) -> games, for matching reports to SportsEngine games."""
    def __init__(self, seasons):
        self.by = collections.defaultdict(list)
        self.alias = {}
        for s in seasons:
            g0 = "men" if s["key"] == "men" else "women"
            names = {norm(t[0]) for t in s["teams"].values()}
            for i, g in enumerate(s["games"]):
                loc = datetime.datetime.fromisoformat(g[0].replace("Z", "+00:00")).astimezone(ZoneInfo(g[1]))
                for side, tid, oid in (("h", g[3], g[4]), ("a", g[4], g[3])):
                    t, o = s["teams"].get(tid), s["teams"].get(oid)
                    if not t:
                        continue
                    self.by[(g0, loc.date(), norm(t[0]))].append(
                        {"season": s["key"], "game": i, "side": side, "team": t[0], "opp": norm(o[0]) if o else "",
                         "mins": loc.hour * 60 + loc.minute, "score": g[5] if side == "h" else g[6]})
            self.alias[g0] = names

    def team_key(self, gender, name):
        k = norm(name)
        if k in self.alias[gender]:
            return k
        hits = [n for n in self.alias[gender] if n.startswith(k) or k.startswith(n)]
        return hits[0] if len(hits) == 1 else k

    def find(self, gender, date, team, opp="", mins=None, days=(0, -1, 1, -2, 2)):
        if not date:
            return None
        t = self.team_key(gender, team)
        o = self.team_key(gender, opp) if opp else ""
        for delta in days:
            c = self.by.get((gender, date + datetime.timedelta(days=delta), t), [])
            if not c:
                continue
            if o:
                same_opp = [x for x in c if x["opp"] == o]
                if same_opp:
                    c = same_opp
                elif delta:
                    continue
            if len(c) > 1 and mins is not None:
                c = sorted(c, key=lambda x: abs(x["mins"] - mins))
            return c[0]
        return None


def read_sheet(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    h = [x.strip().lower() for x in rows[0]]
    col = lambda name, default: h.index(name) if name in h else default
    c = {"ts": 0, "uid": col("game uid", 1), "conf": col("conference", 2), "date": col("game date", 3), "time": col("game time", 4),
         "opp": col("opponent", 5), "team": col("reporting team", 6), "kind": col("player/staff", 7), "name": col("name", 8),
         "event": col("event", 9), "cs": col("clean sheet", 10)}
    out = []
    for r in rows[1:]:
        r = r + [""] * (12 - len(r))
        if not r[c["event"]].strip() or r[c["event"]].strip().lower() == "no stats reported":
            continue
        out.append({k: r[v].strip() for k, v in c.items()})
    return out


def read_cards(text):
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    out = []
    for r in rows:
        reason = (r.get("Reason") or "").strip()
        out.append({"date": r.get("Date", ""), "gender": (r.get("Gender") or "").strip().lower(), "team": r.get("Team", ""),
                    "name": (r.get("Player Name") or "").strip(), "reason": reason,
                    "type": "yc" if reason.lower() in YELLOW_REASONS else "rc"})
    return out


def same_person(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    pa, pb = a.lower().split(), b.lower().split()
    return bool(pa and pb) and re.sub(r"[^a-z]", "", pa[-1]) == re.sub(r"[^a-z]", "", pb[-1]) and pa[0][:1] == pb[0][:1]


def merge(seasons, sheet_text, cards_text):
    """Returns (box, totals, review). box[season][game] = {"h": [...], "a": [...]} with player rows
    [name, g, a, yc, rc, cs]; totals[season][(team_norm, player_norm)] = [name, team, g, a, yc, rc, cs, games]."""
    idx = GameIndex(seasons)
    review = collections.defaultdict(list)
    # ---- sheet: per team-game, per submission
    subs = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in read_sheet(sheet_text):
        gender = "women" if r["conf"].lower().endswith("women") else "men"
        m = idx.find(gender, pdate(r["date"]), r["team"], r["opp"], ptime(r["time"]))
        if not m:
            review["Stat reports that don't match a SportsEngine game"].append(f'{r["date"]} {r["team"]} vs {r["opp"]} ({gender}): {r["name"]} – {r["event"]}')
            continue
        subs[(m["season"], m["game"], m["side"])][r["ts"]].append(r)
    events = collections.defaultdict(lambda: collections.defaultdict(lambda: {"name": "", "g": 0, "a": 0, "yc": 0, "rc": 0, "cs": 0.0, "staff": False}))
    meta = {}
    for key, by_sub in subs.items():
        best = collections.defaultdict(lambda: collections.defaultdict(float))
        names = {}
        for rows in by_sub.values():
            cnt = collections.defaultdict(lambda: collections.defaultdict(float))
            for r in rows:
                p = norm(r["name"]); names.setdefault(p, (r["name"], r["kind"].lower() == "staff"))
                ev = r["event"].lower()
                if ev.startswith("goal"):
                    cnt[p]["g"] += 1
                elif ev.startswith("assist"):
                    cnt[p]["a"] += 1
                elif ev.startswith("yellow"):
                    cnt[p]["yc"] += 1
                elif ev.startswith("red"):
                    cnt[p]["rc"] += 1
                elif ev.startswith("clean"):
                    try:
                        cnt[p]["cs"] += float(r["cs"]) if r["cs"] else 1.0
                    except ValueError:
                        cnt[p]["cs"] += 1.0
            for p, c in cnt.items():
                for k, v in c.items():
                    best[p][k] = max(best[p][k], v)
        for p, c in best.items():
            e = events[key][p]; e["name"], e["staff"] = names[p]
            for k, v in c.items():
                e[k] = v
        meta[key] = len(by_sub)
    # ---- cards CSV is the record; sheet cards only where the CSV has none of that type for that player/game
    sheet_cards = {k: {p: (e["yc"], e["rc"]) for p, e in v.items()} for k, v in events.items()}
    for v in events.values():
        for e in v.values():
            e["yc"] = e["rc"] = 0
    csv_cards = collections.defaultdict(list)
    nationals = 0
    for c in read_cards(cards_text):
        genders = [c["gender"]] if c["gender"] in ("men", "women") else ["men", "women"]
        m = None
        for g in genders:
            m = idx.find(g, pdate(c["date"]), c["team"], days=(0,))   # card dates are official: same day only
            if m:
                break
        if not m and pdate(c["date"]) and NATIONALS[0] <= pdate(c["date"]) <= NATIONALS[1]:
            nationals += 1      # National Championship cards aren't regular season
            continue
        if not m:
            review["Cards (CSV) that don't match a SportsEngine game"].append(f'{c["date"]} {c["team"]}: {c["name"]} – {c["reason"]}')
            continue
        csv_cards[(m["season"], m["game"], m["side"])].append(c)
    for key, cards in csv_cards.items():
        for c in cards:
            p = next((q for q, e in events[key].items() if same_person(e["name"], c["name"])), norm(c["name"]))
            e = events[key][p]
            if not e["name"]:
                e["name"] = c["name"]
            e[c["type"]] += 1
    used_sheet_cards = 0
    for key, per in sheet_cards.items():
        for p, (yc, rc) in per.items():
            e = events[key][p]
            if yc and not e["yc"]:
                e["yc"] = yc; used_sheet_cards += int(yc)
                review["Self-reported cards counted (not in the misconduct CSV)"].append(f'{e["name"]} ({where(seasons, key)}) – yellow')
            if rc and not e["rc"]:
                e["rc"] = rc; used_sheet_cards += int(rc)
                review["Self-reported cards counted (not in the misconduct CSV)"].append(f'{e["name"]} ({where(seasons, key)}) – red')
    # ---- goals vs score check
    for key, per in events.items():
        goals = sum(e["g"] for e in per.values())
        s = next(x for x in seasons if x["key"] == key[0]); g = s["games"][key[1]]
        score = g[5] if key[2] == "h" else g[6]
        if score not in ("", None) and goals > int(score):
            review["Reported goals higher than the team's score (check for duplicates or a wrong game)"].append(
                f"{where(seasons, key)}: {int(goals)} goals reported, score shows {score} ({meta.get(key, 0)} submission(s))")
    # ---- box scores and totals
    box = collections.defaultdict(dict)
    totals = collections.defaultdict(dict)
    games_played = collections.defaultdict(set)
    for (season, gi, side), per in events.items():
        rows = []
        team = team_name(seasons, season, gi, side)
        for p, e in per.items():
            if not (e["g"] or e["a"] or e["yc"] or e["rc"] or e["cs"]):
                continue
            rows.append([e["name"] + (" (staff)" if e["staff"] else ""), e["g"], e["a"], e["yc"], e["rc"], round(e["cs"], 2)])
            if e["staff"]:
                continue
            k = (norm(team), p)
            t = totals[season].setdefault(k, [e["name"], team, 0, 0, 0, 0, 0.0, 0])
            for i, f in ((2, "g"), (3, "a"), (4, "yc"), (5, "rc"), (6, "cs")):
                t[i] += e[f]
            games_played[(season,) + k].add(gi)
        rows.sort(key=lambda r: (-r[1], -r[2], r[0]))
        if rows:
            box[season].setdefault(gi, {})[side] = rows
    for (season, *k), gs in games_played.items():
        totals[season][tuple(k)][7] = len(gs)
    review["_summary"] = [f"{sum(len(v) for v in subs.values())} stat submissions matched to {len(subs)} team-games; "
                          f"{sum(len(v) for v in csv_cards.values())} CSV cards matched ({nationals} National Championship cards left out); {used_sheet_cards} self-reported cards counted"]
    return box, totals, review


def team_name(seasons, season, gi, side):
    s = next(x for x in seasons if x["key"] == season); g = s["games"][gi]
    return s["teams"][g[3] if side == "h" else g[4]][0]


def where(seasons, key):
    s = next(x for x in seasons if x["key"] == key[0]); g = s["games"][key[1]]
    loc = datetime.datetime.fromisoformat(g[0].replace("Z", "+00:00")).astimezone(ZoneInfo(g[1]))
    return f'{loc:%b %-d} {s["teams"][g[3]][0]} vs {s["teams"][g[4]][0]}, {team_name(seasons, key[0], key[1], key[2])}'


def review_markdown(review):
    out = ["# Stats review", "", "Items from the stat sheet and the card CSV that need a look. The page updates on the next refresh after a fix.", ""]
    for line in review.get("_summary", []):
        out += [line, ""]
    for k, v in review.items():
        if k == "_summary":
            continue
        out += [f"## {k} ({len(v)})", ""] + [f"- {x}" for x in v] + [""]
    return "\n".join(out)
