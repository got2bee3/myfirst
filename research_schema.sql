PRAGMA foreign_keys = ON;
CREATE TABLE run_metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE source_files (
 source_id INTEGER PRIMARY KEY, source_url TEXT NOT NULL, retrieved_at_utc TEXT,
 sha256 TEXT NOT NULL, raw_csv BLOB NOT NULL
);
CREATE TABLE teams (
 team TEXT PRIMARY KEY, franchise_name TEXT NOT NULL, conference TEXT NOT NULL,
 division TEXT NOT NULL, historical_aliases_json TEXT NOT NULL
);
CREATE TABLE games (
 game_id TEXT PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES source_files(source_id),
 source_row INTEGER NOT NULL, season INTEGER NOT NULL, week INTEGER NOT NULL,
 game_date TEXT NOT NULL, game_type TEXT NOT NULL, is_playoff INTEGER NOT NULL,
 status TEXT NOT NULL, home_team TEXT NOT NULL REFERENCES teams(team),
 away_team TEXT NOT NULL REFERENCES teams(team), home_abbreviation_raw TEXT NOT NULL,
 away_abbreviation_raw TEXT NOT NULL, home_score REAL, away_score REAL,
 home_moneyline_raw TEXT, away_moneyline_raw TEXT, spread_line_raw TEXT,
 home_spread_odds_raw TEXT, away_spread_odds_raw TEXT,
 is_divisional INTEGER NOT NULL, is_intraconference INTEGER NOT NULL,
 is_interconference INTEGER NOT NULL, raw_json TEXT NOT NULL,
 CHECK(home_team <> away_team)
);
CREATE INDEX games_season_date ON games(season, game_date);
CREATE INDEX games_status ON games(status);
CREATE TABLE market_quotes (
 game_id TEXT NOT NULL REFERENCES games(game_id), market TEXT NOT NULL,
 side TEXT NOT NULL, price_raw TEXT, american_odds REAL, source_type TEXT NOT NULL,
 source_type_raw TEXT, data_source TEXT NOT NULL, original_odds_source TEXT,
 sportsbook TEXT, odds_timestamp TEXT, price_timing TEXT NOT NULL,
 verification_status TEXT NOT NULL,
 PRIMARY KEY(game_id, market, side),
 CHECK(market IN ('moneyline','spread')), CHECK(side IN ('home','away'))
);
CREATE TABLE team_games (
 game_id TEXT NOT NULL REFERENCES games(game_id), team TEXT NOT NULL REFERENCES teams(team),
 opponent TEXT NOT NULL REFERENCES teams(team), season INTEGER NOT NULL, week INTEGER NOT NULL,
 date TEXT NOT NULL, game_type TEXT NOT NULL, game_status TEXT NOT NULL, venue TEXT NOT NULL,
 is_divisional INTEGER NOT NULL, is_intraconference INTEGER NOT NULL, is_interconference INTEGER NOT NULL,
 score REAL, opponent_score REAL, moneyline REAL, opponent_moneyline REAL,
 market_probability REAL, market_status TEXT NOT NULL, result TEXT NOT NULL, profit REAL,
 team_spread REAL, opponent_spread REAL, spread_odds REAL, opponent_spread_odds REAL,
 spread_status TEXT NOT NULL, spread_result TEXT NOT NULL, spread_profit REAL,
 spread_market_probability REAL,
 moneyline_available INTEGER NOT NULL, moneyline_pair_available INTEGER NOT NULL,
 spread_line_available INTEGER NOT NULL, spread_available INTEGER NOT NULL,
 spread_pair_available INTEGER NOT NULL,
 moneyline_implied_probability REAL, spread_implied_probability REAL,
 moneyline_bet_status TEXT NOT NULL, moneyline_placed_stake REAL NOT NULL,
 moneyline_refunded_stake REAL NOT NULL, moneyline_settled_stake REAL NOT NULL,
 moneyline_gross_return REAL,
 spread_bet_status TEXT NOT NULL, spread_placed_stake REAL NOT NULL,
 spread_refunded_stake REAL NOT NULL, spread_settled_stake REAL NOT NULL,
 spread_gross_return REAL,
 PRIMARY KEY(game_id,team)
);
CREATE INDEX team_games_team_season ON team_games(team,season);
CREATE INDEX team_games_status ON team_games(game_status);
CREATE TABLE betting_summary (
 team TEXT NOT NULL REFERENCES teams(team), market TEXT NOT NULL, split TEXT NOT NULL,
 season INTEGER NOT NULL, stats_json TEXT NOT NULL,
 PRIMARY KEY(team, market, split, season)
);
CREATE TABLE validation_checks (
 name TEXT PRIMARY KEY, status TEXT NOT NULL, details_json TEXT NOT NULL
);
CREATE TABLE validation_issues (
 issue_id INTEGER PRIMARY KEY, severity TEXT NOT NULL, code TEXT NOT NULL,
 game_id TEXT, source_row INTEGER, details_json TEXT NOT NULL
);
CREATE VIEW completed_games AS SELECT * FROM games WHERE status='completed';
CREATE VIEW future_games AS SELECT * FROM games WHERE status='future';
CREATE VIEW unsettled_games AS SELECT * FROM games WHERE status<>'completed';
CREATE VIEW completed_team_games AS SELECT * FROM team_games WHERE game_status='completed';
CREATE VIEW unsettled_team_games AS SELECT * FROM team_games WHERE game_status<>'completed';
