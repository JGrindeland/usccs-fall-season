# USCCS 2026 Fall Regular Season page

Live at https://2026-usccs-fall-season.netlify.app/ (embedded on collegeclubsoccer.com).

- `scripts/pull.py` pulls schedules, results, standings and player stats from SportsEngine's public season-microsite feed.
- `scripts/build.py` builds `site/index.html` (fonts, crest and team logos are embedded).
- `.github/workflows/refresh.yml` runs both every 30 minutes and commits only when something changed; Netlify deploys each commit.

On-demand refresh: Actions tab → "Refresh season data" → Run workflow.

Display rules: games marked "In progress" in SportsEngine show as Final on the schedule but are not counted in standings (SportsEngine's own standings already exclude them). "TBD" placeholder rows are removed from standings. CSU San Marcos uses the logo in `assets/csusm_logo.webp`.
