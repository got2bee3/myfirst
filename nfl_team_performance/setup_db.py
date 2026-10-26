"""Create missing study tables and verify their structural contract."""
import argparse
from pathlib import Path
import re
import sys
from .db import ConfigurationError, connect, verify_connection

SCHEMA_PATH = Path(__file__).with_name('schema.sql')


def schema_statements():
    text = '\n'.join(line for line in SCHEMA_PATH.read_text().splitlines()
                     if not line.lstrip().startswith('--'))
    return [part.strip() for part in text.split(';') if part.strip()]


def contracts():
    result = {}
    for statement in schema_statements():
        name = re.search(r'CREATE TABLE IF NOT EXISTS (\w+)', statement).group(1)
        columns, indexes, foreign_keys = set(), set(), set()
        for line in statement.splitlines()[1:]:
            line = line.strip()
            match = re.match(r'(\w+)\s+(?:SMALLINT|BIGINT|INT|TINYINT|VARCHAR|CHAR|DATE|DATETIME|ENUM|JSON|TEXT)\b', line)
            if match:
                columns.add(match.group(1))
            match = re.match(r'(?:UNIQUE )?KEY (\w+)', line)
            if match:
                indexes.add(match.group(1))
            match = re.match(r'CONSTRAINT (\w+) FOREIGN KEY', line)
            if match:
                foreign_keys.add(match.group(1))
        result[name] = (columns, indexes | {'PRIMARY'}, foreign_keys)
    return result


def verify_tables(connection, allow_missing=False):
    counts = {}
    with connection.cursor() as cursor:
        for table, (columns, indexes, foreign_keys) in contracts().items():
            cursor.execute('SELECT ENGINE FROM information_schema.TABLES '
                           'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', (table,))
            row = cursor.fetchone()
            if row is None:
                if allow_missing:
                    continue
                raise RuntimeError(f'Missing table: {table}')
            if row[0].upper() != 'INNODB':
                raise RuntimeError(f'{table}: expected InnoDB')
            cursor.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS '
                           'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', (table,))
            actual_columns = {r[0] for r in cursor.fetchall()}
            cursor.execute('SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS '
                           'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', (table,))
            actual_indexes = {r[0] for r in cursor.fetchall()}
            cursor.execute('SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS '
                           "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_TYPE='FOREIGN KEY'", (table,))
            actual_keys = {r[0] for r in cursor.fetchall()}
            if not (columns <= actual_columns and indexes <= actual_indexes and foreign_keys <= actual_keys):
                raise RuntimeError(f'{table}: existing structure differs; a reviewed migration is required')
            cursor.execute(f'SELECT COUNT(*) FROM `{table}`')
            counts[table] = cursor.fetchone()[0]
    return counts


def run(check_only=False):
    connection = connect()
    try:
        details = verify_connection(connection)
        print(f"Connected to {details['database']}; MySQL {details['mysql_version']}")
        if not check_only:
            verify_tables(connection, allow_missing=True)
            with connection.cursor() as cursor:
                for statement in schema_statements():
                    cursor.execute(statement)
        counts = verify_tables(connection)
        for name, count in counts.items():
            print(f'{name}: verified; {count} records')
        print('Connection and schema checks passed. No data inserted or deleted.')
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Read-only connection/schema check')
    args = parser.parse_args()
    try:
        run(args.check_only)
    except ConfigurationError as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:
        # Driver messages can contain connection metadata. Never print their raw text.
        print(f'Database setup/check failed ({type(exc).__name__}). '
              'Check credentials, network access, TLS trust and schema compatibility. '
              'No credential values are logged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
