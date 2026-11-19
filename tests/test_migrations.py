from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app import create_app, db, PhotoGroup
from test_app import app


def test_initial_upgrade_restart_and_downgrade(app):
    with app.app_context():
        with db.engine.connect() as connection:
            assert connection.execute(text('select version_num from alembic_version')).scalar() == '0004'
            assert compare_metadata(MigrationContext.configure(connection), db.metadata) == []
        upgrade()
        downgrade(revision='base')
        assert set(inspect(db.engine).get_table_names()) == {'alembic_version'}
        upgrade()
        assert 'photo_group' in inspect(db.engine).get_table_names()


def test_adopt_existing_database_preserves_records_and_files(tmp_path):
    app = create_app({'SECRET_KEY':'test', 'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'legacy.db'), 'MEDIA_ROOT':str(tmp_path/'media')})
    with app.app_context():
        upgrade(revision='0001')
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO photo_group (id, state, created_at) VALUES (1, 'staging', '2026-01-01 00:00:00')"))
            connection.execute(text('DROP TABLE alembic_version'))
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


def test_project_migration_preserves_existing_library_graph(tmp_path):
    application = create_app({'SECRET_KEY':'test', 'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'existing.db'), 'MEDIA_ROOT':str(tmp_path/'media')})
    from app import Project, PhotoVersion, CampaignDestination
    with application.app_context():
        upgrade(revision='0001')
        statements = [
            "INSERT INTO photo_group VALUES (1, 'final', '2026-01-01 00:00:00')",
            "INSERT INTO platform VALUES (1, 'Network')",
            "INSERT INTO tag_group VALUES (1, 'Safety')",
            "INSERT INTO tag VALUES (1, 'Safe', 1)",
            "INSERT INTO group_tags VALUES (1, 1)",
            "INSERT INTO photo_version VALUES (1, 1, 'Original', 'old.png', '1/old.png', '2026-01-01 00:00:00')",
            "INSERT INTO social_account VALUES (1, 1, 'Account', '@account', '', 1)",
            "INSERT INTO campaign VALUES (1, 1, 1, 'Existing campaign')",
            "INSERT INTO campaign_destination VALUES (1, 1, 1, 'published', '2026-01-02 00:00:00', 'https://example.com/post')",
        ]
        with db.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        image = tmp_path/'media'/'1'/'old.png'
        image.parent.mkdir()
        image.write_bytes(b'original-file-unchanged')
        upgrade()
        photo = db.session.get(PhotoGroup,1)
        assert photo.project_id == Project.query.one().id == 1
        assert photo.project.name == 'Main library'
        assert photo.state == 'final' and photo.tags[0].name == 'Safe'
        assert photo.campaigns[0].version_id == 1
        assert PhotoVersion.query.one().stored_path == '1/old.png'
        assert CampaignDestination.query.one().post_url == 'https://example.com/post'
        assert image.read_bytes() == b'original-file-unchanged'
        db.session.remove()
        downgrade(revision='0001')
        assert 'project_id' not in {column['name'] for column in inspect(db.engine).get_columns('photo_group')}
        upgrade()
        assert PhotoGroup.query.one().project.name == 'Main library'
        assert image.read_bytes() == b'original-file-unchanged'
