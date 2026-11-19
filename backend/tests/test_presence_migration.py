import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def load_migration(filename):
    path=Path(__file__).parents[1]/'migrations/versions'/filename
    spec=importlib.util.spec_from_file_location(path.stem,path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    return migration


def test_additive_presence_migration_preserves_existing_tables():
    migration = load_migration('f0c37b1e5a42_connection_monitoring.py')
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


def test_existing_room_configuration_does_not_opt_in():
    migration = load_migration('70e31e9a522b_require_guard.py')
    with sa.create_engine('sqlite://').begin() as connection:
        connection.exec_driver_sql('CREATE TABLE presence_configs (test_id INTEGER PRIMARY KEY, guard_room_id VARCHAR(36))')
        connection.exec_driver_sql("INSERT INTO presence_configs VALUES (1, 'room-a')")
        with patch.object(migration, 'op', Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            assert connection.exec_driver_sql('SELECT guard_room_id, require_guard FROM presence_configs').one() == ('room-a', False)
            migration.downgrade()
        assert connection.exec_driver_sql('SELECT guard_room_id FROM presence_configs').scalar() == 'room-a'
