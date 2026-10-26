# NFL Team Performance: web interface

The GUI runs independently of MySQL and the prediction model. It reads `data/games.csv`, an included nflverse snapshot. It never imports the prediction application or the MySQL connection module, and creates no database tables. Existing database tools remain available separately.

## Everyday use

Choose a franchise, select all bets/favorites/underdogs, and click **Run team analysis**. The page shows $10 flat-bet profit and ROI, six editable American-odds bands, actual versus no-vig expected wins, season totals, and a complete downloadable game ledger. Regular-season and playoff results can be combined or separated. Historic franchise aliases are combined, including SD/LAC, STL/LA/LAR, OAK/LV and Washington's names.

No eras are assigned. Enter this team's previous/current inclusive date ranges if desired. Previous era requires an end date; current era may remain open-ended. The eras cannot overlap. Era names, comments, and date ranges are remembered separately for each franchise in browser localStorage when you save/run analysis or download a CSV. Changing teams loads that team’s saved details. They are also carried in the page URL, not stored as permanent database definitions. Browser storage is specific to this browser/device and can be cleared. Click Run team analysis after restoring saved details to update the displayed results. Do not put passwords or sensitive information in comments. Download games CSV exports the currently entered filters, era labels/comments, provenance, prices and individual results. Download summary CSV exports all three period totals, favorites/underdogs, six odds bands, and season summaries for the selected period, including era names/comments, sample sizes, stake, net profit, ROI percentage, and no-vig expectations. Upload either CSV to ChatGPT; the summary is the smaller overview. Missing/undefined era results remain blank, not invented zeros. User-entered spreadsheet formula prefixes are escaped.

The default six price ranges are suggested, not a final study specification. Five editable boundaries generate six mutually exclusive ranges; each boundary belongs to the lower range.

**Refresh historical data** downloads the public nflverse schedule using ordinary HTTPS, validates it, and replaces the data file atomically. A failed download/validation leaves the previous data intact. Concurrent refreshes are rejected using a Linux file lock. No paid odds provider or direct DraftKings endpoint is used. This is historical schedule refresh, not live sportsbook data. Source URL, retrieval timestamp and SHA-256 are recorded in `data/snapshot.json`. The bundled initial timestamp records only the known retrieval date.

A future game with supplied prices is still pending and contributes no return. Completed scores dated after the current New York date are also excluded. Missing team prices do not produce bets. Missing paired prices cannot produce favorite/underdog classifications or no-vig expectations. Ties are assumed void: zero profit, no settled stake and excluded from expected-win comparisons. Betting settlement assumptions may differ by book; this is a documented analytical convention. No automatic bets are placed.

## Local development

Use the existing isolated checkout; do not create a worktree unless requested.

```bash
python -m venv /workspace/nfl-team-performance-venv
/workspace/nfl-team-performance-venv/bin/pip install -r requirements.txt
/workspace/nfl-team-performance-venv/bin/python -m unittest discover -s tests -v
/workspace/nfl-team-performance-venv/bin/python app.py
```

Internal readiness: request the root page and confirm HTTP 200 and `NFL Team Performance`. Do not present localhost addresses as user-facing previews. The development server is for local use, not PythonAnywhere production hosting.

## Separate PythonAnywhere deployment

Do not replace the existing prediction site's WSGI file. A separate web app/domain is required to keep that site intact. The actual separate domain must be confirmed in the Web tab; none is assumed here.

Place the GUI files in `/home/KmayII/nfl_team_performance`:

- `app.py`, `analysis_engine.py`, `requirements.txt`
- `templates/index.html`, `templates/error.html`
- `data/games.csv`, `data/snapshot.json`

The existing `.venv` may be reused after installing the updated `requirements.txt`. Use Python 3.10 or later; the user's existing Python 3.13 environment is compatible with this code. The GUI requires Flask, not database credentials. `NFL_DATA_DIR` optionally selects another writable data directory. `NFL_GUI_SECRET_KEY` optionally supplies a persistent random signing key through the environment (recommended with multiple workers); without it, restart clears browser sessions and may require a page reload before refresh. Do not commit signing keys or environment files.

Set the separate web app's virtualenv to `/home/KmayII/nfl_team_performance/.venv`, and use this WSGI code in that app only:

```python
import sys
project = '/home/KmayII/nfl_team_performance'
if project not in sys.path:
    sys.path.insert(0, project)
from app import app as application
```

Enable Web-tab password protection on the separate site before exposing it. The app relies on hosting-level access control; it does not provide its own login. Use HTTPS. Reload that separate web app, select a team, run analysis, download a CSV and test data refresh. On a network-restricted account, refresh may fail until required source access is available, but the bundled data still works. A PID or successful import alone is not deployment validation.

## Validation performed in the cloud workspace

Tests cover payout arithmetic, vig removal, ties, missing prices, relocation aliases, future-game exclusion, six-band boundaries, all 32 franchise pages, era validation/selection, filtered CSV downloads, refresh CSRF protection, and preservation of old data on refresh failure. Database guard tests run independently. Live HTTP and source-refresh outcomes are reported in the task response. No PythonAnywhere deployment has been performed from this workspace.
