import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_additive_presence_migration_preserves_existing_tables():
    path=Path(__file__).parents[1]/'migrations/versions/f0c37b1e5a42_connection_monitoring.py'
    spec=importlib.util.spec_from_file_location('presence_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine('sqlite://')
    with engine.begin() as connection:
        for table in ['users','tests','attempts']:
            connection.exec_driver_sql(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)')
            connection.exec_driver_sql(f'INSERT INTO {table} VALUES (1)')
        with patch.object(migration,'op',Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            names=set(sa.inspect(connection).get_table_names())
            assert names=={'users','tests','attempts','presence_configs','presence_clients','presence_heartbeats','attempt_presence','presence_events'}
            migration.downgrade()
        assert set(sa.inspect(connection).get_table_names())=={'users','tests','attempts'}
        for table in ['users','tests','attempts']:
            assert connection.exec_driver_sql(f'SELECT id FROM {table}').scalar()==1
