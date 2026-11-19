from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app import create_app, db, PhotoGroup
from test_app import app


def test_initial_upgrade_restart_and_downgrade(app):
    with app.app_context():
        with db.engine.connect() as connection:
            assert connection.execute(text('select version_num from alembic_version')).scalar() == '0001'
            assert compare_metadata(MigrationContext.configure(connection), db.metadata) == []
        upgrade()
        downgrade(revision='base')
        assert set(inspect(db.engine).get_table_names()) == {'alembic_version'}
        upgrade()
        assert 'photo_group' in inspect(db.engine).get_table_names()


def test_adopt_existing_database_preserves_records_and_files(tmp_path):
    app = create_app({'SECRET_KEY':'test', 'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'legacy.db'), 'MEDIA_ROOT':str(tmp_path/'media')})
    with app.app_context():
        db.create_all()  # Simulate the pre-Alembic application.
        db.session.add(PhotoGroup(state='staging'))
        db.session.commit()
    image = tmp_path/'media'/'untouched.png'
    image.write_bytes(b'preserved')
    result = app.test_cli_runner().invoke(args=['adopt-legacy-db'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        upgrade()
        assert PhotoGroup.query.one().state == 'staging'
        assert image.read_bytes() == b'preserved'
    assert app.test_cli_runner().invoke(args=['adopt-legacy-db']).exit_code != 0


def test_adoption_refuses_empty_or_mismatched_schema(tmp_path):
    app = create_app({'SECRET_KEY':'test', 'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'empty.db'), 'MEDIA_ROOT':str(tmp_path/'media')})
    runner = app.test_cli_runner()
    assert runner.invoke(args=['adopt-legacy-db']).exit_code != 0
    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text('create table custom_table (id integer primary key)'))
    result = runner.invoke(args=['adopt-legacy-db'])
    assert result.exit_code != 0
    assert 'does not match' in result.output
    with app.app_context():
        assert inspect(db.engine).get_table_names() == ['custom_table']
