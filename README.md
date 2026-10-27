# NFL Team Performance

## Team analysis GUI

The Flask GUI provides team selection and historical $10 flat-bet moneyline and point-spread analysis without requiring MySQL. Era controls and comparisons have been removed. See [GUI_SETUP.md](GUI_SETUP.md) for use and separate PythonAnywhere deployment. No prediction model code or production database is used.

Independent MySQL storage for historical NFL moneyline analysis. This project does not import or change the NFL prediction model. Phase 1 here creates schema only: no teams, historical games, odds, or eras are seeded.

## Legacy database tools

The sections below document separate, unused database utilities. The GUI does not run migrations or use the legacy `team_eras` table. Removing eras from the GUI performs no database deletions.

## Configuration

Python 3.10+ and MySQL 5.7.8+ (JSON and stored generated columns) are required. The actual PythonAnywhere MySQL version must be confirmed by the connection test.

Run from the repository root, preferably in a PythonAnywhere Bash console where its MySQL service is reachable:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export NFL_DB_HOST='KmayII.mysql.pythonanywhere-services.com'
export NFL_DB_PORT='3306'
export NFL_DB_USER='KmayII'
export NFL_DB_NAME='KmayII$NFL_Team_Performance'
read -r -s -p 'Study database password: ' NFL_DB_PASSWORD
export NFL_DB_PASSWORD
```

The password prompt does not echo or store the value in shell history. Alternatively inject `NFL_DB_PASSWORD` through your secure runtime environment. Do not paste the password into chat, source code, command arguments, or Git. Single quotes around the database name preserve the literal `$`.

`.env.example` documents variable names only. The application does not automatically load `.env` files. Real `.env` files are ignored by Git. Credentials are read only from process environment variables and excluded from settings representations and error output.

Connections require certificate-verified TLS using system trust. Set `NFL_DB_SSL_CA` only if the service supplies a trusted CA file. TLS is not silently disabled. If the server's TLS or external connectivity is unsupported, diagnose that on PythonAnywhere before changing connection policy. A hostname alone does not establish that MySQL is accessible from this cloud machine. No unsupported public port exposure is required.

## Setup and verification

While TLS trust is unresolved, do not run setup. First run this read-only probe:

```bash
python -m nfl_team_performance.test_connection
```

It checks the selected database and executes `SELECT 1` without DDL. Current PythonAnywhere diagnostics report a self-signed certificate in the chain. The official PythonAnywhere help repository inspected during troubleshooting documents the MySQL hostname pattern but does not identify a trusted MySQL CA bundle or fingerprint. Obtain the applicable PEM root/intermediate chain and hostname-verification guidance through authenticated PythonAnywhere support. Do not trust a certificate merely because it was presented by the failing server. Set `NFL_DB_SSL_CA` to the verified bundle's real local path, then rerun the probe. Do not use `CERT_NONE`, `check_hostname=False`, or an SSL dictionary without verified trust.

The default host matches the documented US hostname format. The account's Databases tab remains authoritative. External direct MySQL access is firewalled according to PythonAnywhere documentation; run the probe within PythonAnywhere. These workspace changes are not automatically deployed there.

Report a successful connection test before proceeding with table creation.

```bash
python -m nfl_team_performance.setup_db
python -m nfl_team_performance.setup_db --check-only
python -m unittest discover -s tests -v
```

Setup verifies `SELECT DATABASE(), VERSION()` before executing DDL. Both configuration and connection checks refuse every database name except `KmayII$NFL_Team_Performance`, including `KmayII$default`.

`--check-only` performs read-only connection, table, column/index/foreign-key presence, and row-count checks. Successful setup prints the actual server version and verified tables. Exit code 1 means setup or verification did not complete.

Setup uses only `CREATE TABLE IF NOT EXISTS`. Repeating it does not insert, update, or delete records. Existing tables are checked before creation, and missing structural elements require a separately reviewed migration. The verifier checks expected names/presence, not complete type/index definition equivalence. MySQL DDL auto-commits: a failure can leave some new tables created; correct the prerequisite and rerun. Setup never drops or rebuilds them.

## Schema

All tables use InnoDB and utf8mb4, with restrictive foreign keys (no cascading deletes).

| Table | Purpose / duplicate protection |
|---|---|
| `teams` | Stable franchise ID, unique franchise key and current abbreviation. |
| `team_aliases` | Historical source abbreviations/names and effective date ranges, tied to a franchise; unique source/abbreviation/start date. |
| `games` | Internal stable ID; original source ID; season/week/date/UTC kickoff; game type, generated playoff indicator, teams, scores, status, neutral-site flag. Unique source/source ID plus season/type/week/matchup. |
| `moneylines` | Paired home/away American prices for one market observation; dataset source, nullable original provider and sportsbook, timing, market/retrieval timestamps, import ID. Unique game/observation SHA-256. |
| `team_eras` | Manually assigned name, coach, quarterback, and inclusive start/exclusive end dates. Unique franchise/name and franchise/start date. Empty until explicitly defined. |
| `import_logs` | Import status/timestamps, source URI/checksum, code version, inserted/updated/duplicate/missing/invalid counts, JSON quality report and sanitized error summary. |

The extra `team_aliases` table keeps abbreviation history normalized. SD/LAC, STL/LA/LAR, OAK/LV and Washington's names map to the same respective franchise IDs. Future imports must validate date-effective alias mappings and reject overlapping/conflicting aliases. Current names never replace historical source identifiers.

Moneyline prices and metadata may be NULL when missing. Unknown sportsbook/provider remains NULL; unknown timing is explicitly `unknown`. Source labels must never be inferred as DraftKings, opening, or closing without evidence. Both prices in a row belong to the same market observation. Historical observations are retained, not overwritten.

Future importers must derive `observation_sha256` from a documented canonical representation of source, original source, sportsbook, timing, market timestamp, game identity and both prices (with explicit NULL handling), excluding retrieval time and import-run ID. Repeating identical inputs then cannot duplicate a quote. Source corrections retain a distinct observation; matchup conflicts require reconciliation, not replacement. No importer is implemented yet.

MySQL 5.7 does not enforce CHECK constraints. Future write paths must validate distinct opponents, valid weeks/scores, score/status consistency, American odds (nonzero, absolute value at least 100), at least one price per observation, date range ordering, and nonoverlapping eras/aliases before writes. Foreign keys, uniqueness and unsigned score types are enforced by MySQL. `team_eras` is not a roster history: coach/quarterback fields describe the manually chosen era.

## Later phases

Import 2010 through the current season for all 32 franchises, preserving postseason and source provenance. Report missing odds, duplicates, inconsistent results, and season completeness with cancellation exceptions. Later analysis will select one explicit market observation per game for $10 flat bets, favorite/underdog splits, six user-defined price ranges and market expectations. No era or price-range definitions are assumed here.

## Current verification status

Local unit tests exercise configuration refusal, secret redaction, database identity guards, read-only mode and non-destructive DDL. A live connection, SQL execution, enforced database constraints and repeat-run preservation still require execution against the designated MySQL server. Local tests alone do not establish successful table creation.
