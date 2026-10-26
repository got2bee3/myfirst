import os
import unittest
import ssl
from unittest.mock import patch, MagicMock
from nfl_team_performance.db import DatabaseSettings, ConfigurationError, connect, verify_connection, create_tls_context
from nfl_team_performance.test_connection import test_connection as run_connection_test
from nfl_team_performance.setup_db import contracts, schema_statements, run


class DatabaseTests(unittest.TestCase):
    def test_tls_requires_certificate_and_hostname_verification(self):
        context = create_tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_invalid_custom_ca_does_not_fall_back(self):
        with self.assertRaises(OSError):
            create_tls_context('/nonexistent/nfl-study-ca.pem')

    def test_select_one_is_read_only_and_closes_connection(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [('KmayII$NFL_Team_Performance', '8.0'), (1,)]
        with patch('nfl_team_performance.test_connection.connect', return_value=connection):
            details = run_connection_test()
        self.assertEqual(details['database'], 'KmayII$NFL_Team_Performance')
        self.assertEqual([c.args[0] for c in cursor.execute.call_args_list],
                         ['SELECT DATABASE(), VERSION()', 'SELECT 1'])
        connection.close.assert_called_once()

    def test_missing_password_fails_before_connect(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigurationError):
                connect()

    def test_default_database_is_refused(self):
        settings = DatabaseSettings('host', 3306, 'user', 'KmayII$default', 'test-only')
        with self.assertRaises(ConfigurationError):
            connect(settings)

    def test_password_is_not_in_settings_repr(self):
        self.assertNotIn('test-only', repr(DatabaseSettings('h',3306,'u','db','test-only')))

    def test_connection_identity_checked(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = ('KmayII$default', '8.0')
        with self.assertRaises(ConfigurationError):
            verify_connection(connection)

    def test_wrong_database_stops_before_schema_operations(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = ('KmayII$default', '8.0')
        with patch('nfl_team_performance.setup_db.connect', return_value=connection):
            with self.assertRaises(ConfigurationError):
                run()
        calls = connection.cursor.return_value.__enter__.return_value.execute.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0], 'SELECT DATABASE(), VERSION()')
        connection.close.assert_called_once()

    def test_read_only_mode_never_creates_tables(self):
        connection = MagicMock()
        with patch('nfl_team_performance.setup_db.connect', return_value=connection), \
             patch('nfl_team_performance.setup_db.verify_connection', return_value={'database':'study','mysql_version':'8.0'}), \
             patch('nfl_team_performance.setup_db.verify_tables', return_value={}):
            run(check_only=True)
        connection.cursor.assert_not_called()

    def test_schema_contains_only_non_destructive_table_creation(self):
        statements = schema_statements()
        self.assertEqual(len(statements), 6)
        self.assertTrue(all(s.startswith('CREATE TABLE IF NOT EXISTS ') for s in statements))
        self.assertEqual(set(contracts()), {'teams','team_aliases','games','moneylines','team_eras','import_logs'})
        self.assertIn('home_american', contracts()['moneylines'][0])
        self.assertIn('uq_moneyline_observation', contracts()['moneylines'][1])
        self.assertIn('fk_moneyline_game', contracts()['moneylines'][2])


if __name__ == '__main__':
    unittest.main()
