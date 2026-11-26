"""Physically rotate a managed still image, restoring its bytes on commit failure."""
import hashlib
import logging
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, JpegImagePlugin, PngImagePlugin

logger = logging.getLogger(__name__)


class RotationError(Exception):
    pass


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encode_rotation(source, target, direction):
    with Image.open(source) as original:
        if getattr(original, 'n_frames', 1) != 1:
            raise RotationError('Rotation is supported for still images only; the animated file was not changed.')
        format = original.format
        if format not in ('JPEG', 'PNG', 'WEBP', 'AVIF', 'GIF'):
            raise RotationError('This image format cannot be rotated.')
        image = ImageOps.exif_transpose(original)
        image = image.transpose(Image.Transpose.ROTATE_270 if direction == 'right' else Image.Transpose.ROTATE_90)
        options = {}
        for key in ('icc_profile', 'dpi'):
            if original.info.get(key):
                options[key] = original.info[key]
        exif = image.getexif()
        if exif:
            exif[274] = 1
            if 256 in exif: exif[256] = image.width
            if 257 in exif: exif[257] = image.height
            details = exif.get_ifd(0x8769) if 0x8769 in exif else {}
            if 40962 in details: details[40962] = image.width
            if 40963 in details: details[40963] = image.height
            options['exif'] = exif.tobytes()
        if format == 'JPEG':
            options.update(qtables=original.quantization, subsampling=max(0, JpegImagePlugin.get_sampling(original)))
            if image.info.get('xmp'):
                options['xmp'] = image.info['xmp']
        elif format == 'PNG':
            text = PngImagePlugin.PngInfo()
            for key, value in original.text.items():
                if key != 'XML:com.adobe.xmp':
                    text.add_text(key, value)
            if image.info.get('XML:com.adobe.xmp'):
                text.add_itxt('XML:com.adobe.xmp', image.info['XML:com.adobe.xmp'])
            options['pnginfo'] = text
        elif format == 'WEBP':
            options.update(lossless=True, method=4)
        elif format == 'AVIF':
            options['quality'] = 100
        image.save(target, format=format, **options)


def rotate_version(db, Version, Hash, version, media_root, direction):
    """The caller holds the library write lock, shared with imports and deletions."""
    root = Path(media_root).resolve()
    source = root / version.stored_path
    if source.is_symlink() or source.resolve().parent != (root / str(version.group_id)).resolve() or not source.resolve().is_relative_to(root):
        raise RotationError('Invalid managed image path.')
    source = source.resolve()
    if not source.is_file():
        raise RotationError('The managed image file is missing.')
    paths = []
    backup = None
    replaced = False
    try:
        for prefix in ('.rotating-', '.before-rotate-'):
            descriptor, name = tempfile.mkstemp(prefix=prefix, dir=source.parent)
            os.close(descriptor)
            paths.append(Path(name))
        rotated, backup = paths
        previous_hash = file_hash(source)
        encode_rotation(source, rotated, direction)
        os.chmod(rotated, source.stat().st_mode)
        current_hash = file_hash(rotated)
        duplicate = Version.query.filter(Version.id != version.id, Version.content_hash == current_hash).first()
        alias = db.session.get(Hash, current_hash)
        if duplicate or (alias and alias.version_id != version.id):
            raise RotationError('This rotation would duplicate another image; the file was not changed.')
        for digest in {previous_hash, current_hash, version.content_hash} - {None}:
            if not db.session.get(Hash, digest):
                db.session.add(Hash(digest=digest, version_id=version.id))
        version.content_hash = current_hash
        source.replace(backup)
        replaced = True
        rotated.replace(source)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        if replaced and backup and backup.exists():
            try:
                backup.replace(source)
            except OSError:
                logger.exception('Could not restore image; backup remains at %s', backup)
                paths.remove(backup)  # Never delete the remaining original bytes.
        if isinstance(error, RotationError):
            raise
        raise RotationError('Could not rotate this image. The operation was rolled back.') from error
    finally:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception('Could not clean up a rotation temporary file')
    cache = root / '.previews'
    if cache.resolve() == cache:
        for preview in cache.glob(f'{version.id}-*.webp'):
            try:
                preview.unlink(missing_ok=True)
            except OSError:
                logger.warning('Could not remove stale preview %s', preview)
