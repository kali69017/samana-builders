from django.db import connection
from django.test import TestCase


class SQLiteHardeningSettingsTests(TestCase):
    def test_sqlite_concurrency_options_are_loaded(self):
        options = connection.settings_dict['OPTIONS']
        self.assertEqual(options['timeout'], 20)
        self.assertEqual(options['transaction_mode'], 'IMMEDIATE')
        self.assertIn('PRAGMA journal_mode=WAL', options['init_command'])

    def test_connection_uses_immediate_transactions_and_busy_timeout(self):
        connection.ensure_connection()
        self.assertEqual(connection.transaction_mode, 'IMMEDIATE')
        busy_timeout = connection.connection.execute(
            'PRAGMA busy_timeout').fetchone()[0]
        self.assertGreaterEqual(busy_timeout, 20000)
