"""Bounded HTTP chunks with durable, owner/project-scoped resumable uploads."""
import errno
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
import click
from filelock import FileLock
from flask import abort, g, request, session, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif'}


def register_uploads(app, db, Upload, PhotoGroup, PhotoVersion, store, commit_uploads):
    app.extensions['upload_sessions'] = Upload
    root = Path(app.config['MEDIA_ROOT']) / '.uploads'
    locks = root / 'locks'
    locks.mkdir(parents=True, exist_ok=True)
    chunk_size = app.config['UPLOAD_CHUNK_BYTES']
    if not 1024 * 1024 <= chunk_size <= 16 * 1024 * 1024:
        raise RuntimeError('UPLOAD_CHUNK_SIZE_MB must be between 1 and 16.')

    def lock_for(token):
        return FileLock(str(locks / f'{int(token[:2], 16) % 64:02x}.lock'))

    def part_for(token):
        return root / (token + '.part')

    def owned(token):
        if not re.fullmatch(r'[0-9a-f]{32}', token):
            abort(404)
        return Upload.query.filter_by(id=token, owner=session['sub'], project_id=g.project.id).first_or_404()

    def state(item):
        return {'id': item.id, 'offset': item.received_bytes, 'size': item.total_bytes,
                'chunk_size': item.chunk_bytes, 'status': item.status, 'message': item.message,
                'redirect': url_for('group', id=item.group_id) if item.group_id else url_for('gallery', state='pool')}

    def cleanup():
        cutoff = datetime.utcnow() - timedelta(hours=24)
        tokens = [item.id for item in Upload.query.filter(Upload.updated_at < cutoff).all()]
        removed = 0
        for token in tokens:
            with lock_for(token):
                item = db.session.get(Upload, token, populate_existing=True)
                if item and item.updated_at < cutoff:
                    part_for(token).unlink(missing_ok=True)
                    db.session.delete(item)
                    db.session.commit()
                    removed += 1
        return removed

    @app.cli.command('uploads-cleanup')
    def uploads_cleanup():
        """Remove upload staging files/receipts inactive for 24 hours."""
        click.echo(f'Removed {cleanup()} expired uploads.')

    @app.post('/uploads')
    def upload_start():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict): abort(400)
        token, name, size = payload.get('id'), payload.get('filename'), payload.get('size')
        label, group_id = payload.get('label', 'Original'), payload.get('group_id')
        if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token): abort(400, 'Invalid upload ID.')
        if not isinstance(name, str) or not name or len(name) > 500 or Path(secure_filename(name)).suffix.lower() not in IMAGE_SUFFIXES:
            abort(400, 'Choose a JPG, PNG, GIF, WebP or AVIF image.')
        if type(size) is not int or not 0 < size <= 2**63 - 1: abort(400, 'Invalid file size.')
        if not isinstance(label, str) or not label.strip() or len(label) > 200: abort(400, 'Invalid version label.')
        if group_id is not None:
            if type(group_id) is not int: abort(400)
            PhotoGroup.query.filter_by(id=group_id, project_id=g.project.id).first_or_404()
        cleanup()
        existing = db.session.get(Upload, token)
        if existing:
            existing = owned(token)
            if (existing.filename, existing.total_bytes, existing.group_id) != (name, size, group_id):
                abort(409, 'This upload ID belongs to a different file.')
            if existing.status == 'active' and existing.label != label.strip():
                existing.label = label.strip()
                db.session.commit()
            return state(existing)
        item = Upload(id=token, owner=session['sub'], project_id=g.project.id, group_id=group_id,
                      filename=name, label=label.strip(), total_bytes=size, chunk_bytes=chunk_size)
        db.session.add(item)
        db.session.commit()
        return state(item), 201

    @app.get('/uploads/<token>')
    def upload_status(token):
        return state(owned(token))

    @app.post('/uploads/<token>/chunks')
    def upload_chunk(token):
        if not re.fullmatch(r'[0-9a-f]{32}', token): abort(404)
        with lock_for(token):
            item = owned(token)
            if item.status != 'active': return state(item)
            try: offset = int(request.headers.get('Upload-Offset', ''))
            except ValueError: abort(400, 'Missing upload offset.')
            if offset < 0: abort(400)
            if request.content_length and request.content_length > item.chunk_bytes: abort(413)
            body = request.stream.read(item.chunk_bytes + 1)
            if not body or len(body) > item.chunk_bytes: abort(413, 'Invalid chunk size.')
            if offset + len(body) > item.total_bytes: abort(409, 'Chunk exceeds the declared file size.')
            path = part_for(token)
            if offset < item.received_bytes:
                if not path.exists() or offset + len(body) > item.received_bytes: abort(409, 'Upload offset conflict.')
                with path.open('rb') as source:
                    source.seek(offset)
                    if source.read(len(body)) != body: abort(409, 'Retried chunk does not match uploaded data.')
                return state(item)
            if offset != item.received_bytes: abort(409, 'Upload offset conflict.')
            previous = item.received_bytes
            if previous and (not path.exists() or path.stat().st_size < previous):
                abort(409, 'Uploaded data is missing. Restart this file.')
            try:
                with path.open('r+b' if path.exists() else 'w+b') as target:
                    # Discard a tail written before an interrupted DB commit.
                    target.truncate(previous)
                    target.seek(previous)
                    target.write(body)
                    target.flush()
                    os.fsync(target.fileno())
                item.received_bytes += len(body)
                item.updated_at = datetime.utcnow()
                db.session.commit()
            except Exception as error:
                db.session.rollback()
                if path.exists():
                    with path.open('r+b') as target: target.truncate(previous)
                if isinstance(error, OSError) and error.errno == errno.ENOSPC:
                    abort(507, 'Not enough disk space for this upload.')
                raise
            return state(item)

    @app.post('/uploads/<token>/finish')
    def upload_finish(token):
        if not re.fullmatch(r'[0-9a-f]{32}', token): abort(404)
        with lock_for(token):
            item = owned(token)
            if item.status != 'active': return state(item)
            path = part_for(token)
            if item.received_bytes != item.total_bytes or not path.exists() or path.stat().st_size != item.total_bytes:
                abort(409, 'The upload is incomplete.')
            photo = PhotoGroup.query.filter_by(id=item.group_id, project_id=g.project.id).first_or_404() if item.group_id else None
            new_group = photo is None
            if new_group:
                photo = PhotoGroup(project=g.project, state='pool')
                db.session.add(photo)
                db.session.flush()
            try:
                with path.open('rb') as source:
                    version = store(FileStorage(stream=source, filename=item.filename), photo, item.label, source_path=path)
                db.session.flush()
                item.version_id = version.id
                item.status = 'complete'
            except ValueError as error:
                if new_group: db.session.delete(photo)
                item.status = 'duplicate'
                item.message = str(error)
            item.updated_at = datetime.utcnow()
            commit_uploads()
            path.unlink(missing_ok=True)
            return state(item)

    @app.post('/uploads/<token>/cancel')
    def upload_cancel(token):
        if not re.fullmatch(r'[0-9a-f]{32}', token): abort(404)
        with lock_for(token):
            item = owned(token)
            if item.status == 'active':
                part_for(token).unlink(missing_ok=True)
                item.status = 'cancelled'
                item.updated_at = datetime.utcnow()
                db.session.commit()
            return state(item)
