"""Disposable, private display images. Originals are never rewritten."""
import hashlib
import io
import os
import tempfile
from pathlib import Path

from filelock import FileLock
from PIL import Image, ImageOps, UnidentifiedImageError

VARIANTS = {'display': (2400, 500_000), 'thumb': (640, 100_000)}
POLICY = 'webp-v1'


def encode_proxy(source, variant):
    edge, budget = VARIANTS[variant]
    with Image.open(source) as original:
        # JPEG draft decoding saves memory before the full image is decoded.
        original.draft('RGB', (edge, edge))
        image = ImageOps.exif_transpose(original)
        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        image = image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
        image.info.clear()  # Do not copy EXIF/GPS into previews.
        while True:
            for quality in (85, 75, 65, 55, 45):
                output = io.BytesIO()
                image.save(output, format='WEBP', quality=quality, method=4)
                if output.tell() <= budget:
                    return output.getvalue()
            image = image.resize((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)), Image.Resampling.LANCZOS)


def cached_proxy(media_root, version, variant):
    root = Path(media_root).resolve()
    source = (root / version.stored_path).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise FileNotFoundError('Original image is unavailable.')
    # Coordinate generation with upload/deletion transactions.
    with FileLock(str(root / '.library-write.lock')):
        stat = source.stat()
        signature = hashlib.sha256(f'{POLICY}:{version.stored_path}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:24]
        folder = root / '.previews'
        folder.mkdir(exist_ok=True)
        if folder.resolve() != folder:
            raise ValueError('Invalid preview cache directory.')
        target = folder / f'{version.id}-{signature}-{variant}.webp'
        if target.is_file():
            return target
        payload = encode_proxy(source, variant)
        descriptor, name = tempfile.mkstemp(prefix='.render-', dir=folder)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(payload)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        # Discard stale renditions after a source or encoding-policy change.
        for stale in folder.glob(f'{version.id}-*-{variant}.webp'):
            if stale != target:
                stale.unlink(missing_ok=True)
        return target


PREVIEW_ERRORS = (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError)
PLACEHOLDER = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="640" height="480" fill="#191d1e"/><text x="320" y="240" text-anchor="middle" fill="#a7afb0" font-family="sans-serif" font-size="20">Preview unavailable</text></svg>'
