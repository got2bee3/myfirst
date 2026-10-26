-- No USE, CREATE DATABASE, DROP, ALTER, DELETE, or data inserts.
-- MySQL 5.7+ / InnoDB. UTC DATETIME values where specified.
CREATE TABLE IF NOT EXISTS teams (
    team_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    franchise_key VARCHAR(32) NOT NULL,
    current_name VARCHAR(100) NOT NULL,
    current_abbreviation VARCHAR(8) NOT NULL,
    PRIMARY KEY (team_id),
    UNIQUE KEY uq_teams_franchise (franchise_key),
    UNIQUE KEY uq_teams_abbreviation (current_abbreviation)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS team_aliases (
    alias_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    team_id SMALLINT UNSIGNED NOT NULL,
    source VARCHAR(64) NOT NULL,
    abbreviation VARCHAR(16) NOT NULL,
    historical_name VARCHAR(100) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NULL COMMENT 'Exclusive, NULL means ongoing',
    PRIMARY KEY (alias_id),
    UNIQUE KEY uq_alias_identity (source, abbreviation, valid_from),
    KEY ix_alias_team_dates (team_id, valid_from, valid_to),
    CONSTRAINT fk_alias_team FOREIGN KEY (team_id) REFERENCES teams (team_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS games (
    game_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source VARCHAR(64) NOT NULL,
    source_game_id VARCHAR(100) NOT NULL,
    season SMALLINT UNSIGNED NOT NULL,
    week TINYINT UNSIGNED NOT NULL,
    game_date DATE NOT NULL,
    kickoff_utc DATETIME NULL,
    game_type ENUM('REG','WC','DIV','CON','SB') NOT NULL,
    is_playoff TINYINT(1) GENERATED ALWAYS AS (game_type <> 'REG') STORED,
    home_team_id SMALLINT UNSIGNED NOT NULL,
    away_team_id SMALLINT UNSIGNED NOT NULL,
    home_score SMALLINT UNSIGNED NULL,
    away_score SMALLINT UNSIGNED NULL,
    status ENUM('scheduled','in_progress','final','postponed','canceled','unknown') NOT NULL DEFAULT 'unknown',
    neutral_site TINYINT(1) NULL,
    PRIMARY KEY (game_id),
    UNIQUE KEY uq_game_source (source, source_game_id),
    UNIQUE KEY uq_game_matchup (season, game_type, week, home_team_id, away_team_id),
    KEY ix_games_date (game_date),
    KEY ix_games_home (home_team_id, season, week),
    KEY ix_games_away (away_team_id, season, week),
    CONSTRAINT fk_game_home FOREIGN KEY (home_team_id) REFERENCES teams (team_id),
    CONSTRAINT fk_game_away FOREIGN KEY (away_team_id) REFERENCES teams (team_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS import_logs (
    import_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    started_at_utc DATETIME NOT NULL,
    finished_at_utc DATETIME NULL,
    status ENUM('running','succeeded','failed','validation_failed') NOT NULL,
    source VARCHAR(64) NOT NULL,
    source_uri TEXT NULL,
    source_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    importer_version VARCHAR(100) NULL,
    rows_read INT UNSIGNED NOT NULL DEFAULT 0,
    games_inserted INT UNSIGNED NOT NULL DEFAULT 0,
    games_updated INT UNSIGNED NOT NULL DEFAULT 0,
    moneylines_inserted INT UNSIGNED NOT NULL DEFAULT 0,
    duplicate_rows INT UNSIGNED NOT NULL DEFAULT 0,
    missing_odds_games INT UNSIGNED NOT NULL DEFAULT 0,
    invalid_rows INT UNSIGNED NOT NULL DEFAULT 0,
    quality_report_json JSON NULL,
    error_summary TEXT NULL COMMENT 'Sanitized, never credentials or connection strings',
    PRIMARY KEY (import_id),
    KEY ix_import_source_time (source, started_at_utc),
    KEY ix_import_checksum (source_sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS moneylines (
    moneyline_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    game_id BIGINT UNSIGNED NOT NULL,
    source VARCHAR(64) NOT NULL COMMENT 'Dataset actually retrieved',
    original_odds_source VARCHAR(100) NULL,
    sportsbook VARCHAR(100) NULL,
    price_timing ENUM('opening','closing','snapshot','unknown') NOT NULL DEFAULT 'unknown',
    market_time_utc DATETIME NULL,
    retrieved_at_utc DATETIME NOT NULL,
    home_american INT NULL,
    away_american INT NULL,
    observation_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
        COMMENT 'Canonical source observation identity, excludes retrieval time and import ID',
    import_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (moneyline_id),
    UNIQUE KEY uq_moneyline_observation (game_id, observation_sha256),
    KEY ix_moneyline_selection (game_id, price_timing, market_time_utc),
    KEY ix_moneyline_source_book (source, sportsbook),
    KEY ix_moneyline_import (import_id),
    CONSTRAINT fk_moneyline_game FOREIGN KEY (game_id) REFERENCES games (game_id),
    CONSTRAINT fk_moneyline_import FOREIGN KEY (import_id) REFERENCES import_logs (import_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS team_eras (
    era_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    team_id SMALLINT UNSIGNED NOT NULL,
    era_name VARCHAR(100) NOT NULL,
    head_coach VARCHAR(200) NULL,
    quarterback VARCHAR(200) NULL,
    starts_on DATE NOT NULL,
    ends_before DATE NULL COMMENT 'Exclusive, NULL means ongoing',
    notes TEXT NULL,
    PRIMARY KEY (era_id),
    UNIQUE KEY uq_era_name (team_id, era_name),
    UNIQUE KEY uq_era_start (team_id, starts_on),
    KEY ix_era_dates (team_id, starts_on, ends_before),
    CONSTRAINT fk_era_team FOREIGN KEY (team_id) REFERENCES teams (team_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
