# NFL Team Performance: web interface

The GUI runs independently of MySQL and the prediction model. It reads `data/games.csv`, an included nflverse snapshot. It never imports the prediction application or the MySQL connection module, and creates no database tables. Existing database tools remain available separately.

## Everyday use

Choose a franchise and **Bet type** (Moneyline or Point spread), select all bets/favorites/underdogs and the schedule, then click **Run team analysis**. Analysis covers 2010 through the latest completed games. No era controls, names, comments, or comparisons are used. Old bookmarked era arguments are ignored. Previously saved browser era entries are left untouched but never loaded or used.

Both markets appear in an overview. The selected market drives the headline returns, favorite/underdog splits, and season table. Spread favorites give points, spread underdogs receive points, and pick’em games appear only in the all-games group. Moneyline favorite/underdog classification uses both implied probabilities. The overview applies the chosen favorite/underdog filter independently to each market; its two rows can represent different games. Historic franchise aliases are combined, including SD/LAC, STL/LA/LAR, OAK/LV and Washington’s names.

The ledger and **Download games CSV** contain both moneylines and both teams’ spread odds, selected-team and opponent spreads, cover/no-cover/push results, and separate $10 moneyline/spread profits. These are the games selected by the active market’s filters. **Download summary CSV** contains the two market overviews plus active-market splits and season results, with no eras. Six editable American moneyline price bands appear only in moneyline mode. Each of the five cutoffs belongs to the lower range. Upload either CSV to ChatGPT for analysis.

Spread convention: nflverse’s `spread_line` is the home team’s expected winning margin. The selected team’s handicap is `-spread_line` at home and `spread_line` away. A positive `score - opponent_score + team_spread` covers; zero pushes; negative fails to cover. Spread classification can be calculated even when a price is missing, but financial results require the actual recorded spread price. Missing lines remain unknown; missing odds are never replaced with -110. Covers/non-covers/pushes for all available lines are displayed separately from the priced-bet record.

A winning $10 bet earns `10 * odds / 100` for positive American odds or `10 * 100 / abs(odds)` for negative odds; a losing bet loses $10. Moneyline ties and spread pushes are void, with zero net and no settled stake. A tied game can still cover a nonzero spread. The two sides’ implied probabilities are normalized to remove vig. Spread expected covers refer to non-push outcomes, with pushes excluded, not a model prediction. Missing paired spread prices exclude the game from expected-cover comparisons but not realized returns if its own price exists. These settlement assumptions are analytical conventions, not independently verified sportsbook rules.

**Refresh historical data** downloads the public nflverse schedule using ordinary HTTPS, validates it, and replaces the data file atomically. A failed download/validation leaves the previous data intact. Concurrent refreshes are rejected using a Linux file lock. No paid odds provider or direct DraftKings endpoint is used. This is historical schedule refresh, not live sportsbook data. Source URL, retrieval timestamp and SHA-256 are recorded in `data/snapshot.json`. The bundled initial timestamp records only the known retrieval date.

A future game with supplied prices is still pending and contributes no return. Completed scores dated after the current New York date are also excluded. Missing team prices do not produce bets. Missing paired moneyline prices cannot produce moneyline favorite/underdog classifications. Missing paired prices in either market cannot produce no-vig expectations. Ties are assumed void: zero profit, no settled stake and excluded from expected-win comparisons. Betting settlement assumptions may differ by book; this is a documented analytical convention. No automatic bets are placed.

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

Place the GUI files in `/home/KmayII/nfl_team_performance_gui`:

- `app.py`, `analysis_engine.py`, `requirements.txt`
- `templates/index.html`, `templates/error.html`
- `data/games.csv`, `data/snapshot.json`

The existing `.venv` may be reused after installing the updated `requirements.txt`. Use Python 3.10 or later; the user's existing Python 3.13 environment is compatible with this code. The GUI requires Flask, not database credentials. `NFL_DATA_DIR` optionally selects another writable data directory. `NFL_GUI_SECRET_KEY` optionally supplies a persistent random signing key through the environment (recommended with multiple workers); without it, restart clears browser sessions and may require a page reload before refresh. Do not commit signing keys or environment files.

Set the separate web app's virtualenv to `/home/KmayII/nfl_team_performance_gui/.venv`, and use this WSGI code in that app only:

```python
import sys
project = '/home/KmayII/nfl_team_performance_gui'
if project not in sys.path:
    sys.path.insert(0, project)
from app import app as application
```

Enable Web-tab password protection on the separate site before exposing it. The app relies on hosting-level access control; it does not provide its own login. Use HTTPS. Reload that separate web app, select a team, run analysis, download a CSV and test data refresh. On a network-restricted account, refresh may fail until required source access is available, but the bundled data still works. A PID or successful import alone is not deployment validation.

## Validation performed in the cloud workspace

Tests cover payout arithmetic, vig removal, ties, missing prices, relocation aliases, future-game exclusion, six-band boundaries, all 32 franchise pages, spread orientation, push handling, actual-price payouts, missing spread data, legacy-era argument handling, filtered CSV downloads, refresh CSRF protection, and preservation of old data on refresh failure. Database guard tests run independently. Live HTTP and source-refresh outcomes are reported in the task response. No PythonAnywhere deployment has been performed from this workspace.
