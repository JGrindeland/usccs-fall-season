#!/usr/bin/env python3
"""Build the USCCS regular-season page (schedules, results, standings, stats) from data/*.json
(written by scripts/pull.py from SportsEngine's public season microsite feed). Output: site/index.html"""
import json, base64, pathlib, datetime, sys, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import stats as statmerge

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = ROOT / "data"
ASSETS = ROOT / "assets"
def b64(p): return base64.b64encode(open(p, "rb").read()).decode()
raw = json.load(open(HERE / "data.json"))
LOGOS = json.load(open(HERE / "logos.json"))   # team logos, 64px webp, embedded as data URIs
import re
norm = lambda n: re.sub(r"[^a-z0-9]", "", n.lower())
LOGO_OVERRIDE = {"csusanmarcos": "data:image/webp;base64," + b64(ASSETS / "csusm_logo.webp")}   # supplied by Jordan, Nov 23
DROP_STANDINGS = {"tbd"}   # placeholder rows removed from standings (e.g. Men Midwest South)
PL = json.load(open(HERE / "players.json"))   # re-pulled one team at a time (stable paging)
_read = lambda n: (HERE / n).read_text(encoding="utf-8") if (HERE / n).exists() else ""
BOX, TOT, REVIEW = statmerge.merge(raw["seasons"], _read("sheet_stats.csv"), _read("cards.csv"))   # USCCS stat sheet + misconduct CSV


# ---------- compact the data ----------
out = {"pulled": raw["pulled"], "seasons": []}
for s in raw["seasons"]:
    divname = {d[0]: d[1].strip() for d in s["divs"]}
    tids = list(s["teams"].keys())
    tix = {t: i for i, t in enumerate(tids)}
    divs = sorted(set(divname.values()))
    dix = {d: i for i, d in enumerate(divs)}
    teams = [[s["teams"][t][0], dix.get(divname.get(s["teams"][t][1], ""), -1), LOGO_OVERRIDE.get(norm(s["teams"][t][0]), LOGOS.get(s["teams"][t][2], ""))] for t in tids]
    tzs = sorted({g[1] for g in s["games"]})
    games = []
    for gi, g in enumerate(s["games"]):
        if g[3] not in tix or g[4] not in tix: continue
        b = BOX.get(s["key"], {}).get(gi)
        games.append([g[0][:16], tzs.index(g[1]), g[2], tix[g[3]], tix[g[4]],
                      g[5] if g[5] != "" else None, g[6] if g[6] != "" else None, g[7], g[9],
                      [b.get("h", []), b.get("a", [])] if b else 0])      # box: rows [name, G, A, YC, RC, CS]
    name2team = {}
    for i, t in enumerate(teams): name2team.setdefault(norm(t[0]), i)
    for nm in {p[1] for p in PL[s["key"]]} | {r[0] for n in s["standings"] for r in n["rows"]}:   # truncated names, e.g. "Milwaukee School of Engin"
        k = norm(nm)
        if k and k not in name2team:
            hits = [i for i, t in enumerate(teams) if norm(t[0]).startswith(k)]
            if len(hits) == 1: name2team[k] = hits[0]
    stand = []
    for n in s["standings"]:
        d = divname.get(n["div"], "")
        rows = [[name2team.get(norm(r[0]), -1), r[0]] + [r[k] or 0 for k in (1, 2, 3, 4, 7, 5, 6, 8, 9, 10)] for r in n["rows"] if norm(r[0]) not in DROP_STANDINGS]
        stand.append([dix.get(d, -1), rows])     # rows: team, name, P W L D GD GF GA Pts YC RC
    # Standings are computed from the game results (Jordan, Nov 23), not taken from SportsEngine's table,
    # which can be stale (it still counted e.g. Butler 3-0 Cleveland State after that game went back to "in progress").
    #  * only games marked Final ("completed") with both scores count; "in progress", scheduled/delayed-with-score don't
    #  * a game between teams from different standings tables (e.g. Rocky Mountain vs Southwest) doesn't count
    #  * 3 points for a win, 1 for a draw; GD capped at 5 per game (SportsEngine's setting)
    #  * order: points, head-to-head points among tied teams, goal difference, goals for, then name
    for _, rows in stand:
        for r in rows: r[2:12] = [0] * 10
    rowof = {r[0]: r for _, rows in stand for r in rows if r[0] >= 0}
    divblk = {blk[0]: blk for blk in stand}
    h2h = collections.defaultdict(list)
    for g in s["games"]:
        if g[3] not in tix or g[4] not in tix or g[5] == "" or g[6] == "": continue
        dh, da = s["teams"][g[3]][1], s["teams"][g[4]][1]
        if g[2] != "completed":
            if g[2] not in ("in_progress", "cancelled", "postponed"):
                REVIEW["Games with a score but not marked Final in SportsEngine (left out of standings)"].append(
                    f"{g[0][:10]} {s['teams'][g[3]][0]} {g[5]}–{g[6]} {s['teams'][g[4]][0]} ({g[2]})")
            continue
        hs, as_ = int(g[5]), int(g[6])
        if dh != da:
            REVIEW["Cross-division games left out of standings (they still show on the schedule)"].append(
                f"{g[0][:10]} {s['teams'][g[3]][0]} ({divname.get(dh, '?').strip()}) {hs}–{as_} {s['teams'][g[4]][0]} ({divname.get(da, '?').strip()})")
            continue
        for tid, gf, ga in ((g[3], hs, as_), (g[4], as_, hs)):
            ti = tix[tid]; r = rowof.get(ti)
            if r is None:     # team missing from SportsEngine's table: add it to its division's table
                blk = divblk.get(dix.get(divname.get(dh, "").strip(), -1))
                if blk is None: continue
                r = [ti, s["teams"][tid][0]] + [0] * 10; blk[1].append(r); rowof[ti] = r
            r[2] += 1; r[7] += gf; r[8] += ga; r[6] += max(-5, min(5, gf - ga))
            if gf > ga: r[3] += 1; r[9] += 3
            elif gf < ga: r[4] += 1
            else: r[5] += 1; r[9] += 1
        h2h[dh].append((tix[g[3]], tix[g[4]], hs, as_))
    for d_i, rows in stand:
        games_here = h2h.get(next((k for k, v in divname.items() if v.strip() == (divs[d_i] if d_i >= 0 else None)), None), [])
        by_pts = collections.defaultdict(list)
        for r in rows: by_pts[r[9]].append(r)
        ordered = []
        for pts in sorted(by_pts, reverse=True):
            grp = by_pts[pts]
            if len(grp) > 1:
                ids = {r[0] for r in grp}; hp = collections.Counter()
                for a, b, x, y in games_here:
                    if a in ids and b in ids:
                        hp[a] += 3 if x > y else 1 if x == y else 0; hp[b] += 3 if y > x else 1 if x == y else 0
                grp.sort(key=lambda r: (-hp[r[0]], -r[6], -r[7], r[1]))
            ordered += grp
        rows[:] = ordered
    # season player totals: goals/assists = the higher of SportsEngine's total and the stat-sheet total (never added); cards = misconduct CSV only
    merged = collections.defaultdict(list)
    for (tk, pk), t in TOT.get(s["key"], {}).items():
        merged[name2team.get(tk, name2team.get(norm(t[1]), -1))].append(t)
    players, used = [], set()
    for p in PL[s["key"]]:
        if norm(p[1]) not in name2team: continue
        ti = name2team[norm(p[1])]
        m = next((t for t in merged.get(ti, []) if id(t) not in used and statmerge.same_person(t[0], p[0])), None)
        if m: used.add(id(m))
        mt = m or [p[0], "", 0, 0, 0, 0, 0.0, 0]
        players.append([p[0], ti, max(p[2], mt[7]), max(p[3], mt[2]), max(p[4], mt[3]), mt[4], mt[5], round(mt[6], 2)])   # cards: misconduct CSV only
    for ti, lst in merged.items():
        if ti < 0: continue
        for t in lst:
            if id(t) not in used:
                players.append([t[0], ti, t[7], t[2], t[3], t[4], t[5], round(t[6], 2)])
    players = [p for p in players if any(p[3:])]
    # team cards (players + staff, every game with a card record incl. "in progress") and games played incl. "in progress"
    tcards = {}
    inprog = collections.Counter()
    for gi, g in enumerate(s["games"]):
        if g[3] not in tix or g[4] not in tix: continue
        b = BOX.get(s["key"], {}).get(gi, {})
        for side, tid in (("h", g[3]), ("a", g[4])):
            t = tcards.setdefault(tix[tid], [0, 0, 0])
            if g[2] in ("completed", "in_progress") and g[5] != "" and g[6] != "": t[2] += 1
            if g[2] == "in_progress": inprog[tix[tid]] += 1
            for r in b.get(side, []): t[0] += r[3]; t[1] += r[4]
    # games played for discipline = every scored game marked Final or "in progress" (cross-division included)
    out["seasons"].append({"key": s["key"], "label": "Men" if s["key"] == "men" else "Women", "name": s["name"],
                           "divs": divs, "teams": teams, "tz": tzs, "games": games, "stand": stand, "players": players,
                           "tcards": {str(k): v for k, v in tcards.items() if v[0] or v[1] or v[2]}})

(HERE / "review.md").write_text(statmerge.review_markdown(REVIEW))
DATA = json.dumps(out, separators=(",", ":"))
pulled = datetime.datetime.fromisoformat(raw["pulled"].replace("Z", "+00:00")).astimezone(__import__("zoneinfo").ZoneInfo("America/Chicago"))
UPDATED = pulled.strftime("%b %-d, %Y, %-I:%M %p %Z")

F = {n: b64(ASSETS / f"Industry-{n}.woff2") for n in ["Book", "Medium", "Demi", "Black"]}
CREST = b64(ASSETS / "crest160.png")

html = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>USCCS 2026 Regular Season</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
@font-face{font-family:IndBook;src:url(data:font/woff2;base64,__FBOOK__) format('woff2');font-display:swap}
@font-face{font-family:IndMed;src:url(data:font/woff2;base64,__FMED__) format('woff2');font-display:swap}
@font-face{font-family:IndDemi;src:url(data:font/woff2;base64,__FDEMI__) format('woff2');font-display:swap}
@font-face{font-family:IndBlack;src:url(data:font/woff2;base64,__FBLACK__) format('woff2');font-display:swap}
:root{
  --navy:#11213F;--sky:#6BC4E8;--gold:#E7C247;
  --bg:#F2F5F9;--surface:#FFFFFF;--surface2:#F7F9FC;--fg:#11213F;--muted:#55657F;--line:#D9E0EA;--line2:#EDF1F6;
  --band:#11213F;--bandfg:#FFFFFF;--accent:#1F8FC2;--win:#E9F6FC;--warn:#8A5A00;--warnbg:#FFF4D6;--bad:#B42318;--badbg:#FDECEA;--chip:#E6EBF2;--seltab:#11213F;--seltabfg:#FFFFFF;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0A1222;--surface:#121D33;--surface2:#16233D;--fg:#E7EDF6;--muted:#9AA9C2;--line:#263755;--line2:#1C2A45;
  --band:#081022;--bandfg:#FFFFFF;--accent:#6BC4E8;--win:#16314A;--warn:#F3C969;--warnbg:#3A2E12;--bad:#FF8A80;--badbg:#3A1A1A;--chip:#1E2C48;--seltab:#6BC4E8;--seltabfg:#0A1222;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0A1222;--surface:#121D33;--surface2:#16233D;--fg:#E7EDF6;--muted:#9AA9C2;--line:#263755;--line2:#1C2A45;
  --band:#081022;--bandfg:#FFFFFF;--accent:#6BC4E8;--win:#16314A;--warn:#F3C969;--warnbg:#3A2E12;--bad:#FF8A80;--badbg:#3A1A1A;--chip:#1E2C48;--seltab:#6BC4E8;--seltabfg:#0A1222;color-scheme:dark}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--fg);font-family:IndMed,"Arial Narrow",Arial,sans-serif;font-size:15px;line-height:1.35}
.wrap{max-width:1180px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
header.band{background:var(--band);color:var(--bandfg);border-bottom:6px solid var(--gold)}
header .wrap{display:flex;align-items:center;gap:18px;padding-block:16px}
header .crest{height:96px;width:auto;flex:none}
.kick{font-family:IndDemi,Arial,sans-serif;color:var(--sky);letter-spacing:.16em;font-size:12px;text-transform:uppercase}
h1{font-family:IndBlack,"Arial Black",sans-serif;font-size:clamp(24px,4.4vw,40px);line-height:1;margin:4px 0;letter-spacing:.01em;text-wrap:balance;text-transform:uppercase}
.sub{font-family:IndDemi,Arial,sans-serif;color:var(--gold);font-size:13px;letter-spacing:.1em;text-transform:uppercase}
.upd{font-family:IndBook,Arial,sans-serif;color:#C9D3E3;font-size:12px;margin-top:6px}
.bar{background:var(--surface);border-bottom:1px solid var(--line);position:sticky;top:env(safe-area-inset-top,0px);z-index:5}
.bar .wrap{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding-block:10px}
.seg{display:inline-flex;background:var(--chip);border-radius:10px;padding:3px;gap:2px}
.seg button{border:0;background:transparent;color:var(--muted);font-family:IndDemi,Arial,sans-serif;font-size:13px;letter-spacing:.08em;text-transform:uppercase;padding:8px 14px;border-radius:8px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--seltab);color:var(--seltabfg)}
.tabs{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}
.tabs button{flex:none;border:0;background:transparent;color:var(--muted);font-family:IndDemi,Arial,sans-serif;font-size:13px;letter-spacing:.08em;text-transform:uppercase;padding:9px 12px;border-radius:8px;cursor:pointer;border-bottom:3px solid transparent}
.tabs button[aria-selected="true"]{color:var(--fg);border-bottom-color:var(--gold);border-radius:8px 8px 0 0}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding-block:14px 6px}
select,input[type=search]{font-family:IndMed,Arial,sans-serif;font-size:14px;color:var(--fg);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-width:0}
select{max-width:100%}
input[type=search]{flex:1 1 180px}
.reset{border:1px solid var(--line);background:var(--surface);color:var(--muted);font-family:IndDemi,Arial,sans-serif;font-size:12px;letter-spacing:.08em;text-transform:uppercase;padding:8px 12px;border-radius:8px;cursor:pointer}
.note{font-family:IndBook,Arial,sans-serif;color:var(--muted);font-size:13px;margin:4px 0 12px}
main{padding-bottom:28px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,520px),1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden;min-width:0}
.card h3{margin:0;padding:10px 14px;background:var(--surface2);border-bottom:1px solid var(--line);font-family:IndBlack,Arial,sans-serif;font-size:16px;letter-spacing:.04em;text-transform:uppercase;display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.card h3 small{font-family:IndDemi,Arial,sans-serif;font-size:11px;color:var(--muted);letter-spacing:.1em}
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-family:IndDemi,Arial,sans-serif;font-size:11px;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;font-weight:normal;text-align:center;padding:7px 6px;border-bottom:1px solid var(--line)}
td{padding:7px 6px;border-bottom:1px solid var(--line2);text-align:center;font-size:14px}
tr:last-child td{border-bottom:0}
th.l,td.l{text-align:left}
td.rk{color:var(--muted);width:28px;font-family:IndDemi,Arial,sans-serif}
td.pts{font-family:IndBlack,Arial,sans-serif}
.tm{display:flex;align-items:center;gap:8px;min-width:0}
.tm button{all:unset;cursor:pointer;font-family:IndDemi,Arial,sans-serif;overflow-wrap:anywhere}
.tm button:hover,.tm button:focus-visible{color:var(--accent);text-decoration:underline}
.lg{width:24px;height:24px;border-radius:6px;object-fit:contain;background:#fff;flex:none;border:1px solid var(--line2)}
.ini{width:24px;height:24px;border-radius:6px;flex:none;display:grid;place-items:center;background:var(--chip);color:var(--muted);font-family:IndDemi,Arial,sans-serif;font-size:10px}
tr.me td{background:var(--win)}
.day{margin:18px 0 8px;font-family:IndBlack,Arial,sans-serif;font-size:15px;letter-spacing:.06em;text-transform:uppercase;display:flex;align-items:center;gap:10px}
.day::after{content:"";flex:1;height:1px;background:var(--line)}
.games{display:grid;gap:8px}
.g{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:grid;grid-template-columns:96px minmax(0,1fr) 74px minmax(0,1fr);gap:6px 12px;align-items:center}
.g .when{font-family:IndDemi,Arial,sans-serif;font-size:12px;color:var(--muted);letter-spacing:.04em}
.g .when b{display:block;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin-top:2px}
.g .h{justify-content:flex-end;text-align:right}
.g .a{justify-content:flex-start}
.g .h .tm{flex-direction:row-reverse}
.sc{font-family:IndBlack,Arial,sans-serif;font-size:20px;text-align:center;letter-spacing:.04em;white-space:nowrap}
.sc.vs{font-family:IndDemi,Arial,sans-serif;font-size:12px;color:var(--muted);letter-spacing:.12em}
.win .tm button{font-family:IndBlack,Arial,sans-serif}
.g .lose .tm button{color:var(--muted)}
.meta{grid-column:2 / -1;font-family:IndBook,Arial,sans-serif;font-size:12px;color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 10px;justify-content:center}
.tag{font-family:IndDemi,Arial,sans-serif;font-size:10px;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:99px;background:var(--chip);color:var(--muted)}
.tag.warn{background:var(--warnbg);color:var(--warn)}
.tag.bad{background:var(--badbg);color:var(--bad)}
.more{display:block;margin:14px auto 0;border:1px solid var(--line);background:var(--surface);color:var(--fg);font-family:IndDemi,Arial,sans-serif;font-size:12px;letter-spacing:.08em;text-transform:uppercase;padding:10px 16px;border-radius:8px;cursor:pointer}
.empty{padding:24px;text-align:center;color:var(--muted);font-family:IndBook,Arial,sans-serif}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:4px 0 14px}
.sum div{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.sum b{display:block;font-family:IndBlack,Arial,sans-serif;font-size:22px}
.sum span{font-family:IndDemi,Arial,sans-serif;font-size:11px;letter-spacing:.1em;color:var(--muted);text-transform:uppercase}
.bxbtn{all:unset;cursor:pointer;font-family:IndDemi,Arial,sans-serif;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
.bxbtn:hover,.bxbtn:focus-visible{text-decoration:underline}
.box{grid-column:1 / -1;display:grid;grid-template-columns:1fr 1fr;gap:10px 18px;border-top:1px solid var(--line2);padding-top:10px;margin-top:2px}
.box h4{margin:0 0 4px;font-family:IndDemi,Arial,sans-serif;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.box ul{list-style:none;margin:0;padding:0;display:grid;gap:3px;font-size:13px}
.box li{display:flex;gap:6px;align-items:center;min-width:0;overflow-wrap:anywhere}
.box .n{font-family:IndDemi,Arial,sans-serif}
.box .x{color:var(--muted);font-family:IndBook,Arial,sans-serif}
.ic{flex:none;display:inline-block;width:14px;text-align:center;font-family:IndBlack,Arial,sans-serif;font-size:11px;color:var(--muted)}
.cd{flex:none;display:inline-block;width:9px;height:12px;border-radius:2px;margin:0 2.5px}
.cd.y{background:#F2C200}.cd.r{background:#D92D20}
.box .none{color:var(--muted);font-family:IndBook,Arial,sans-serif;font-size:12px}
@media (max-width:640px){.box{grid-template-columns:1fr}}
footer{font-family:IndBook,Arial,sans-serif;color:var(--muted);font-size:12px;padding-block:8px 20px}
@media (max-width:640px){
  header .crest{height:64px}
  header .wrap{gap:12px}
  .g{grid-template-columns:minmax(0,1fr) 58px minmax(0,1fr)}
  .g .when{grid-column:1 / -1;display:flex;gap:8px;align-items:baseline}
  .g .when b{display:inline;margin:0}
  .meta{grid-column:1 / -1}
  .sc{font-size:18px}
  .hide-sm{display:none}
  .bar{position:static}
  .filters{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .filters input[type=search]{grid-column:1 / -1}
  .sub{font-size:11px}
  td,th{padding:6px 4px}
}
</style></head><body>
<header class="band"><div class="wrap">
  <img class="crest" src="data:image/png;base64,__CREST__" alt="USCCS crest">
  <div><div class="kick">US College Club Soccer</div><h1>2026 Fall Regular Season</h1>
  <div class="sub">Schedules · Results · Standings · Stats</div>
  <div class="upd">Data from SportsEngine · last change __UPDATED__</div></div>
</div></header>
<div class="bar"><div class="wrap">
  <div class="seg" role="group" aria-label="Gender">
    <button data-g="0" aria-pressed="true">Men</button><button data-g="1" aria-pressed="false">Women</button>
  </div>
  <div class="tabs" role="tablist">
    <button role="tab" data-t="stand" aria-selected="true">Standings</button>
    <button role="tab" data-t="sched" aria-selected="false">Schedule &amp; Results</button>
    <button role="tab" data-t="stats" aria-selected="false">Stats</button>
  </div>
</div></div>
<main class="wrap">
  <div class="filters">
    <select id="fDiv" aria-label="Division"></select>
    <select id="fTeam" aria-label="Team"></select>
    <select id="fWhen" aria-label="Order"><option value="asc">Oldest first</option><option value="desc">Newest first</option></select>
    <input type="search" id="fQ" placeholder="Search teams or players" aria-label="Search">
    <button class="reset" id="reset">Reset</button>
  </div>
  <div id="view"></div>
</main>
<footer class="wrap">Schedules, results and standings from SportsEngine; goal difference follows SportsEngine's standings settings. Goals, assists and clean sheets also come from USCCS team stat reports, and cards only from the misconduct record. Each player's goals and assists use the higher of SportsEngine and those reports, so nothing is counted twice.</footer>
<script>
const DATA = __DATA__;
const S = {g:0, tab:"stand", div:"", team:"", q:"", order:"asc", limit:120, open:new Set()};
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const sea = () => DATA.seasons[S.g];
const ini = n => n.replace(/[^A-Za-z ]/g,"").split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]).join("").toUpperCase();
function logo(t){ const T = sea().teams[t]; if (!T) return `<span class="ini">?</span>`;
  return T[2] ? `<img class="lg" src="${T[2]}" alt="" onerror="this.outerHTML='<span class=&quot;ini&quot;>${esc(ini(T[0]))}</span>'">` : `<span class="ini">${esc(ini(T[0]))}</span>`; }
function tm(t, name){ const T = sea().teams[t]; const n = T ? T[0] : name;
  return `<span class="tm">${t>=0?logo(t):`<span class="ini">${esc(ini(n||""))}</span>`}<button data-team="${t}" title="Show ${esc(n)}">${esc(n)}</button></span>`; }
const matchQ = s => !S.q || s.toLowerCase().includes(S.q.toLowerCase());
const teamDiv = t => (sea().teams[t]||[])[1];

function fillFilters(){
  const s = sea();
  $("#fDiv").innerHTML = `<option value="">All divisions (${s.divs.length})</option>` + s.divs.map((d,i)=>`<option value="${i}">${esc(d)}</option>`).join("");
  $("#fDiv").value = S.div;
  fillTeams();
}
function fillTeams(){
  const s = sea(); let list = s.teams.map((t,i)=>[t[0],i]).filter(x=>S.div===""||s.teams[x[1]][1]==+S.div).sort((a,b)=>a[0].localeCompare(b[0]));
  $("#fTeam").innerHTML = `<option value="">All teams</option>` + list.map(([n,i])=>`<option value="${i}">${esc(n)}</option>`).join("");
  if (S.team!=="" && !list.some(x=>x[1]==+S.team)) S.team = "";
  $("#fTeam").value = S.team;
}

function standings(){
  const s = sea();
  let blocks = s.stand.filter(([d])=>S.div===""||d==+S.div).sort((a,b)=>(s.divs[a[0]]||"").localeCompare(s.divs[b[0]]||""));
  if (S.team!=="") blocks = blocks.filter(([,rows])=>rows.some(r=>r[0]==+S.team));
  if (S.q) blocks = blocks.filter(([d,rows])=>matchQ(s.divs[d]||"")||rows.some(r=>matchQ(r[1])));
  if (!blocks.length) return `<div class="empty">No standings match these filters.</div>`;
  return `<div class="grid">` + blocks.map(([d,rows])=>`<section class="card"><h3>${esc(s.divs[d]||"Division")}<small>${rows.length} teams</small></h3><div class="tw"><table>
    <thead><tr><th></th><th class="l">Team</th><th>P</th><th>W</th><th>L</th><th>D</th><th>GD</th><th class="hide-sm">GF</th><th class="hide-sm">GA</th><th>Pts</th></tr></thead><tbody>
    ${rows.map((r,i)=>`<tr class="${S.team!==""&&r[0]==+S.team?"me":""}"><td class="rk">${i+1}</td><td class="l">${tm(r[0],r[1])}</td><td>${r[2]}</td><td>${r[3]}</td><td>${r[4]}</td><td>${r[5]}</td><td>${r[6]>0?"+":""}${r[6]}</td><td class="hide-sm">${r[7]}</td><td class="hide-sm">${r[8]}</td><td class="pts">${r[9]}</td></tr>`).join("")}
    </tbody></table></div></section>`).join("") + `</div>`;
}

const fmtCache = {};
function fmt(tz, opts){ const k = tz+JSON.stringify(opts); return fmtCache[k] ||= new Intl.DateTimeFormat("en-US",{timeZone:tz,...opts}); }
function gameList(){
  const s = sea();
  let gs = s.games.map((g,i)=>({g,i})).filter(({g})=>{
    if (S.div!=="" && teamDiv(g[3])!=+S.div && teamDiv(g[4])!=+S.div) return false;
    if (S.team!=="" && g[3]!=+S.team && g[4]!=+S.team) return false;
    if (S.q && !matchQ(s.teams[g[3]][0]) && !matchQ(s.teams[g[4]][0]) && !matchQ(g[7]||"")) return false;
    return true; });
  gs.sort((a,b)=> S.order==="asc" ? a.g[0].localeCompare(b.g[0]) : b.g[0].localeCompare(a.g[0]));
  return gs;
}
function boxSide(rows, team){
  const R = rows||[], list = (f) => R.filter(f);
  const nm = r => `<span class="n">${esc(r[0])}</span>`;
  const goals = list(r=>r[1]>0).map(r=>`<li><span class="ic">G</span>${nm(r)}${r[1]>1?` <span class="x">×${r[1]}</span>`:""}</li>`);
  const ast = list(r=>r[2]>0).map(r=>`<li><span class="ic">A</span>${nm(r)}${r[2]>1?` <span class="x">×${r[2]}</span>`:""}</li>`);
  const cards = list(r=>r[3]>0||r[4]>0).map(r=>`<li>${'<span class="cd y" title="Yellow card"></span>'.repeat(r[3])}${'<span class="cd r" title="Red card"></span>'.repeat(r[4])}${nm(r)}</li>`);
  const cs = list(r=>r[5]>0).map(r=>`<li><span class="ic">CS</span>${nm(r)}${r[5]<1?` <span class="x">(shared ${r[5]})</span>`:""}</li>`);
  const all = [...goals,...ast,...cards,...cs];
  return `<div><h4>${esc(team)}</h4>${all.length?`<ul>${all.join("")}</ul>`:`<span class="none">No stats reported</span>`}</div>`;
}
function boxHTML(g){ const s = sea(); return `<div class="box">${boxSide(g[9][0], s.teams[g[3]][0])}${boxSide(g[9][1], s.teams[g[4]][0])}</div>`; }
function schedule(){
  const s = sea(); const gs = gameList();
  if (!gs.length) return `<div class="empty">No games match these filters.</div>`;
  const played = gs.filter(x=>x.g[5]!=null&&x.g[6]!=null).length;
  let html = `<p class="note">${gs.length} games · ${played} with scores. Times are local to the venue.</p>`; let last = "";
  for (const {g,i} of gs.slice(0, S.limit)){
    const tz = s.tz[g[1]], d = new Date(g[0]+":00Z");
    const day = fmt(tz,{weekday:"long",month:"long",day:"numeric"}).format(d);
    if (day!==last){ html += (last?`</div>`:"") + `<div class="day">${esc(day)}</div><div class="games">`; last = day; }
    const time = g[8] ? "TBD" : fmt(tz,{hour:"numeric",minute:"2-digit",timeZoneName:"short"}).format(d);
    const has = g[5]!=null && g[6]!=null, hs=+g[5], as=+g[6];
    const st = g[2];
    const tag = (st==="completed"||st==="in_progress")?"Final":st==="postponed"?"Postponed":st==="cancelled"?"Cancelled":st==="delayed"?"Delayed":"Scheduled";
    const cls = (st==="postponed"||st==="cancelled")?"bad":"";
    const dv = s.divs[teamDiv(g[3])] || "";
    html += `<div class="g"><div class="when">${esc(time)}<b>${esc(tag)}</b></div>
      <div class="h ${has&&hs>as?"win":has&&hs<as?"lose":""}" style="display:flex">${tm(g[3])}</div>
      <div class="sc ${has?"":"vs"}">${has?`${hs} – ${as}`:"vs"}</div>
      <div class="a ${has&&as>hs?"win":has&&as<hs?"lose":""}" style="display:flex">${tm(g[4])}</div>
      <div class="meta">${dv?`<span class="tag">${esc(dv)}</span>`:""}${cls?`<span class="tag ${cls}">${esc(tag)}</span>`:""}${g[7]?`<span>${esc(g[7])}</span>`:""}${g[9]?`<button class="bxbtn" data-box="${i}" aria-expanded="${S.open.has(i)}">${S.open.has(i)?"Hide":"Box score"}</button>`:""}</div>
      ${g[9]&&S.open.has(i)?boxHTML(g):""}</div>`;
  }
  html += `</div>`;
  if (gs.length > S.limit) html += `<button class="more" id="more">Show more games (${gs.length - S.limit} left)</button>`;
  return html;
}

function stats(){
  const s = sea();
  let P = s.players.filter(p=>(S.div===""||teamDiv(p[1])==+S.div)&&(S.team===""||p[1]==+S.team)&&(!S.q||matchQ(p[0])||matchQ(s.teams[p[1]][0])));
  // team numbers from standings
  let T = []; for (const [d,rows] of s.stand) for (const r of rows) if (r[0]>=0 && (S.div===""||d==+S.div) && (S.team===""||r[0]==+S.team) && (!S.q||matchQ(r[1]))) T.push(r);
  const cs = {}; for (const g of s.games) if (g[5]!=null&&g[6]!=null&&g[2]==="completed"){ if(+g[6]===0) cs[g[3]]=(cs[g[3]]||0)+1; if(+g[5]===0) cs[g[4]]=(cs[g[4]]||0)+1; }
  // team cards include staff and every game with a card record (also "in progress" games); games played counts those too
  const TD = {}; for (const [k,v] of Object.entries(s.tcards)){ const t=+k; if ((S.div===""||teamDiv(t)==+S.div)&&(S.team===""||t==+S.team)&&(!S.q||matchQ(s.teams[t][0]))) TD[t]=[t,v[0],v[1],v[2]]; }
  const goals = P.reduce((a,p)=>a+p[3],0), gf = T.reduce((a,r)=>a+r[7],0), yc = Object.values(TD).reduce((a,t)=>a+t[1],0), rc = Object.values(TD).reduce((a,t)=>a+t[2],0);
  const fmtCS = v => Number.isInteger(v) ? v : v.toFixed(2).replace(/0+$/,"");
  const lead = (title, rows, cols) => `<section class="card"><h3>${title}</h3><div class="tw"><table><thead><tr><th></th>${cols.map(c=>`<th class="${c[2]||""}">${c[0]}</th>`).join("")}</tr></thead><tbody>
     ${rows.length?rows.map((r,i)=>`<tr><td class="rk">${i+1}</td>${cols.map(c=>`<td class="${c[2]||""}">${c[1](r)}</td>`).join("")}</tr>`).join(""):`<tr><td colspan="${cols.length+1}" class="empty">Nothing recorded yet.</td></tr>`}</tbody></table></div></section>`;
  const top = (arr,key,n=15) => arr.filter(r=>key(r)>0).sort((a,b)=>key(b)-key(a)||a[0].localeCompare?.(b[0])).slice(0,n);
  const pl = r => `<span style="font-family:IndDemi,Arial,sans-serif">${esc(r[0])}</span>`;
  const pt = r => tm(r[1]);
  const per = (a,b) => b ? (a/b).toFixed(2) : "–";
  return `<div class="sum"><div><b>${P.filter(p=>p[3]>0).length}</b><span>Players with a goal</span></div><div><b>${goals}</b><span>Player goals recorded</span></div><div><b>${gf}</b><span>Team goals (standings)</span></div><div><b>${yc}</b><span>Yellow cards</span></div><div><b>${rc}</b><span>Red cards</span></div></div>
  <div class="grid">
   ${lead("Top scorers", top(P,r=>r[3]), [["Player",pl,"l"],["Team",pt,"l hide-sm"],["GP",r=>r[2]],["G",r=>`<b>${r[3]}</b>`],["A",r=>r[4]]])}
   ${lead("Top assists", top(P,r=>r[4]), [["Player",pl,"l"],["Team",pt,"l hide-sm"],["GP",r=>r[2]],["A",r=>`<b>${r[4]}</b>`],["G",r=>r[3]]])}
   ${lead("Best attack", T.filter(r=>r[2]).sort((a,b)=>b[7]/b[2]-a[7]/a[2]||b[7]-a[7]).slice(0,15), [["Team",r=>tm(r[0],r[1]),"l"],["P",r=>r[2]],["GF",r=>r[7]],["Per game",r=>`<b>${per(r[7],r[2])}</b>`]])}
   ${lead("Best defense", T.filter(r=>r[2]).sort((a,b)=>a[8]/a[2]-b[8]/b[2]||(cs[b[0]]||0)-(cs[a[0]]||0)).slice(0,15), [["Team",r=>tm(r[0],r[1]),"l"],["P",r=>r[2]],["GA",r=>r[8]],["Per game",r=>`<b>${per(r[8],r[2])}</b>`],["Clean sheets",r=>cs[r[0]]||0]])}
   ${lead("Clean sheets (goalkeepers)", top(P,r=>r[7]), [["Player",pl,"l"],["Team",pt,"l hide-sm"],["GP",r=>r[2]],["CS",r=>`<b>${fmtCS(r[7])}</b>`]])}
   ${lead("Discipline", top(P,r=>r[5]+r[6]*3,15), [["Player",pl,"l"],["Team",pt,"l hide-sm"],["Yellow",r=>r[5]],["Red",r=>r[6]]])}
   ${lead("Team discipline", Object.values(TD).filter(t=>t[1]+t[2]>0&&t[3]>0).map(t=>[...t,(t[1]+t[2])/t[3]]).sort((a,b)=>b[4]-a[4]||(b[1]+b[2])-(a[1]+a[2])||b[2]-a[2]).slice(0,15), [["Team",r=>tm(r[0]),"l"],["GP",r=>r[3]],["Yellow",r=>r[1]],["Red",r=>r[2]],["Cards per game",r=>`<b>${per(r[1]+r[2],r[3])}</b>`]])}
  </div>`;
}

function render(){
  $("#fWhen").style.display = S.tab==="sched" ? "" : "none";
  $("#view").innerHTML = S.tab==="stand" ? standings() : S.tab==="sched" ? schedule() : stats();
  const m = $("#more"); if (m) m.onclick = () => { S.limit += 200; render(); };
}
document.addEventListener("click", e => {
  const bx = e.target.closest("[data-box]"); if (bx){ const i=+bx.dataset.box; S.open.has(i)?S.open.delete(i):S.open.add(i); const y=window.scrollY; render(); window.scrollTo(0,y); return; }
  const b = e.target.closest("[data-team]"); if (b && +b.dataset.team>=0){ S.team = b.dataset.team; const d = teamDiv(+S.team); S.div = d>=0?String(d):""; S.q=""; $("#fQ").value=""; fillFilters(); S.limit=120; render(); window.scrollTo({top:0,behavior:"smooth"}); }
});
document.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{ S.g=+b.dataset.g; S.div=""; S.team=""; S.limit=120;
  document.querySelectorAll(".seg button").forEach(x=>x.setAttribute("aria-pressed", x===b)); fillFilters(); render(); });
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{ S.tab=b.dataset.t; S.limit=120;
  document.querySelectorAll(".tabs button").forEach(x=>x.setAttribute("aria-selected", x===b)); render(); });
$("#fDiv").onchange = e => { S.div = e.target.value; fillTeams(); S.limit=120; render(); };
$("#fTeam").onchange = e => { S.team = e.target.value; S.limit=120; render(); };
$("#fWhen").onchange = e => { S.order = e.target.value; S.limit=120; render(); };
let qt; $("#fQ").oninput = e => { clearTimeout(qt); qt = setTimeout(()=>{ S.q = e.target.value.trim(); S.limit=120; render(); }, 180); };
$("#reset").onclick = () => { S.div=""; S.team=""; S.q=""; $("#fQ").value=""; S.limit=120; fillFilters(); render(); };
fillFilters(); render();
// auto-height for the SportsEngine iframe embed
(function(){ function s(){ try{ parent.postMessage({usccsSeasonHeight: Math.ceil(document.body.getBoundingClientRect().height)+2}, "*"); }catch(e){} }
  new ResizeObserver(s).observe(document.body); addEventListener("load", s); document.fonts && document.fonts.ready.then(s); })();
</script></body></html>"""

html = (html.replace("__FBOOK__", F["Book"]).replace("__FMED__", F["Medium"]).replace("__FDEMI__", F["Demi"]).replace("__FBLACK__", F["Black"])
        .replace("__CREST__", CREST).replace("__UPDATED__", UPDATED).replace("__DATA__", DATA))
site = ROOT / "site"; site.mkdir(exist_ok=True)
(site / "index.html").write_text(html)
print("built site/index.html", len(html))
