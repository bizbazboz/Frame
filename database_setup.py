"""Explicit, schema-checked adoption of libraries created before Alembic."""
import click
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from flask_migrate import stamp
from sqlalchemy import MetaData, create_engine, inspect


def register_database_commands(app, db):
    @app.cli.command('adopt-legacy-db')
    def adopt_legacy_db():
        """Validate the original schema and mark it as revision 0001 without changing data."""
        config = app.extensions['migrate'].migrate.get_config()
        baseline = ScriptDirectory.from_config(config).get_revision('0001')
        reference = create_engine('sqlite:///:memory:')
        try:
            with reference.begin() as connection:
                with Operations.context(MigrationContext.configure(connection)):
                    baseline.module.upgrade()
                metadata = MetaData()
                metadata.reflect(bind=connection)
            with db.engine.connect() as connection:
                tables = set(inspect(connection).get_table_names())
                if 'alembic_version' in tables:
                    raise click.ClickException('Database already has migration tracking; use flask db upgrade.')
                if not tables:
                    raise click.ClickException('Database is empty; use flask db upgrade.')
                context = MigrationContext.configure(connection, opts={'compare_type': True})
                if compare_metadata(context, metadata):
                    raise click.ClickException('Schema does not match revision 0001; no adoption was performed.')
            stamp(revision='0001')
            click.echo('Existing library adopted at revision 0001. Run flask db upgrade next.')
        finally:
            reference.dispose()
