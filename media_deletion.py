"""Delete only the managed files tracked by a photo record, with rollback staging."""
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class MediaDeletionError(Exception):
    pass


def delete_with_media(db, record, versions, media_root):
    root = Path(media_root).resolve()
    paths = []
    folders = set()
    for version in versions:
        folder = (root / str(version.group_id)).resolve()
        path = (root / version.stored_path).resolve()
        if not folder.is_relative_to(root) or folder == root or path.parent != folder:
            raise MediaDeletionError('Invalid managed image path.')
        if path.exists() and not path.is_file():
            raise MediaDeletionError('Managed image path is not a file.')
        paths.append(path)
        folders.add(folder)
        preview_folder = (root / '.previews').resolve()
        if not preview_folder.is_relative_to(root) or preview_folder == root:
            raise MediaDeletionError('Invalid preview cache path.')
        if preview_folder.is_dir():
            for preview in preview_folder.glob(f'{version.id}-*.webp'):
                if preview.is_symlink() or not preview.is_file():
                    raise MediaDeletionError('Invalid preview cache file.')
                paths.append(preview)
            folders.add(preview_folder)
    staging = Path(tempfile.mkdtemp(prefix='.deleting-', dir=root))
    moved = []
    try:
        for index, path in enumerate(paths):
            if path.exists():
                staged = staging / str(index)
                path.replace(staged)
                moved.append((path, staged))
        records = record if isinstance(record, (list, tuple)) else [record]
        for item in records:
            db.session.delete(item)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        for original, staged in reversed(moved):
            try:
                staged.replace(original)
            except OSError:
                logger.exception('Could not restore a staged image after deletion failed')
        try:
            staging.rmdir()
        except OSError:
            pass
        raise MediaDeletionError('Deletion failed; the database change was rolled back.') from error
    # The records are committed. Any cleanup failure leaves quarantined files, never live references.
    for _, staged in moved:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            logger.exception('Could not remove a staged deleted image')
    for folder in folders | {staging}:
        try:
            folder.rmdir()  # Empty directories only; untracked images are preserved.
        except OSError:
            pass
