# USCCS 2026 Fall Regular Season page

Live at https://2026-usccs-fall-season.netlify.app/ (embedded on collegeclubsoccer.com).

- `scripts/pull.py` pulls schedules, results, standings and player stats from SportsEngine's public season-microsite feed.
- `scripts/build.py` builds `site/index.html` (fonts, crest and team logos are embedded).
- `.github/workflows/refresh.yml` runs both every 30 minutes and commits only when something changed; Netlify deploys each commit.

On-demand refresh: Actions tab → "Refresh season data" → Run workflow.

Stats from USCCS reports:
- Goals, assists and clean sheets come from the live stat Google sheet (RAWresponses tab, link-viewable); each refresh downloads it to `data/sheet_stats.csv`.
- Yellow/red cards come from the misconduct export in `data/cards.csv` (replace the file to update; National Championship dates Nov 11–15 are left out). Card type comes from the reason (cautions = yellow; 2nd caution, violent conduct, abusive language, DOGSO, serious foul play, spitting = red).
- Cards come only from the CSV (self-reported cards in the sheet are ignored). SportsEngine's score is the record: reported goals above a team's score are dropped. Repeat submissions for a team-game aren't added together (per player, the highest count in any one submission). Each player's season numbers take the higher of SportsEngine and these reports.
- `data/review.md` lists anything that couldn't be matched.

Display rules:
- A game between teams from different standings tables (e.g. Rocky Mountain vs Southwest) doesn't count in standings; it still shows on the schedule. SportsEngine counts these when they're Final, so the build takes them back out (listed in `data/review.md`). games marked "In progress" in SportsEngine show as Final on the schedule but are not counted in standings (SportsEngine's own standings already exclude them). "TBD" placeholder rows are removed from standings. CSU San Marcos uses the logo in `assets/csusm_logo.webp`.

Netlify site: 2026-usccs-fall-season (publishes `site/` from `main`).
