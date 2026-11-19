"""Read-only image inspection for the authenticated Pool review screen."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import warnings

from PIL import ExifTags, Image, ImageCms, IptcImagePlugin

IPTC_NAMES = {(2, 5): 'Object name', (2, 25): 'Keywords', (2, 55): 'Date created',
              (2, 60): 'Time created', (2, 80): 'Byline', (2, 90): 'City',
              (2, 95): 'Province / state', (2, 101): 'Country', (2, 105): 'Headline',
              (2, 110): 'Credit', (2, 115): 'Source', (2, 116): 'Copyright',
              (2, 120): 'Caption', (2, 122): 'Caption writer'}


def display_value(value):
    if isinstance(value, bytes):
        try:
            text = value.decode('utf-8').strip('\x00')
            if any(ord(c) < 32 and c not in '\t\n\r' for c in text):
                return f'Binary data ({len(value):,} bytes)'
            return text[:2000]
        except UnicodeDecodeError:
            return f'Binary data ({len(value):,} bytes)'
    if isinstance(value, (list, tuple)):
        return ', '.join(display_value(item) for item in value[:100])[:2000]
    if isinstance(value, dict):
        return '; '.join(f'{key}: {display_value(item)}' for key, item in list(value.items())[:100])[:2000]
    return str(value)[:2000]


def flatten(value, prefix=''):
    rows = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f'{prefix} / {key}' if prefix else str(key)
            rows.extend(flatten(item, path))
            if len(rows) >= 500:
                break
    else:
        rows.append((prefix, display_value(value)))
    return rows[:500]


def inspect_image(media_root, stored_path):
    root = Path(media_root).resolve()
    path = (root / stored_path).resolve()
    if not path.is_relative_to(root):
        return {'sections': [], 'histogram': None, 'error': 'Image file unavailable.'}
    try:
        stat = path.stat()
    except OSError:
        return {'sections': [], 'histogram': None, 'error': 'Image file unavailable.'}
    return _inspect(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=128)
def _inspect(path, modified_ns, size):
    sections = []
    result = {'sections': sections, 'histogram': None, 'error': None}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                rows = [('Format', image.format or 'Unknown'), ('Dimensions', f'{width:,} × {height:,} px'),
                        ('Megapixels', f'{width * height / 1_000_000:.2f} MP'), ('Colour mode', image.mode),
                        ('Channels', ', '.join(image.getbands())), ('Frames', str(getattr(image, 'n_frames', 1)))]
                sections.append(('Image', rows))
                info = image.info.copy()
                exif = image.getexif()
                if exif:
                    sections.append(('EXIF', [(ExifTags.TAGS.get(key, str(key)), display_value(value))
                                              for key, value in sorted(exif.items()) if key not in (34665, 34853)]))
                    for name, ifd, names in [('Camera EXIF', 34665, ExifTags.TAGS), ('GPS', 34853, ExifTags.GPSTAGS), ('Interoperability', 40965, ExifTags.TAGS)]:
                        try:
                            nested = exif.get_ifd(ifd)
                            if nested:
                                sections.append((name, [(names.get(key, str(key)), display_value(value)) for key, value in sorted(nested.items())]))
                        except (KeyError, OSError, ValueError, TypeError, SyntaxError):
                            pass
                try:
                    iptc = IptcImagePlugin.getiptcinfo(image)
                    if iptc:
                        sections.append(('IPTC', [(IPTC_NAMES.get(key, f'{key[0]}:{key[1]}'), display_value(value)) for key, value in sorted(iptc.items())]))
                except (OSError, ValueError, TypeError, SyntaxError):
                    pass
                try:
                    xmp = image.getxmp()
                    if xmp:
                        sections.append(('XMP', flatten(xmp)))
                except Exception:
                    # A malformed metadata packet must not block review decisions.
                    if info.get('xmp'):
                        sections.append(('XMP', [('Packet', display_value(info['xmp']))]))
                profile = info.get('icc_profile')
                if profile:
                    try:
                        name = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(BytesIO(profile))).strip()
                    except (OSError, ValueError, TypeError):
                        name = f'Embedded profile ({len(profile):,} bytes)'
                    sections.append(('Colour profile', [('ICC profile', name)]))
                extra = [(str(key), display_value(value)) for key, value in info.items()
                         if key not in ('exif', 'icc_profile', 'xmp', 'XML:com.adobe.xmp')]
                if extra:
                    sections.append(('Embedded metadata', extra[:500]))
                # Keep inspection fast for large originals; the chart is explicitly labelled as sampled.
                image.thumbnail((1024, 1024))
                rgb = image.convert('RGB')
                values = rgb.histogram()
                bins = [values[offset:offset + 256] for offset in (0, 256, 512)]
                peak = max(max(channel) for channel in bins) or 1
                paths = ['M 0 100 ' + ' '.join(f'L {i} {100 - count / peak * 96:.3f}' for i, count in enumerate(channel)) + ' L 255 100 Z' for channel in bins]
                result['histogram'] = {'paths': paths, 'bins': bins, 'sample_size': rgb.size, 'frame': 1}
    except (OSError, ValueError, TypeError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        result['error'] = 'Image analysis unavailable.'
    result['sections'] = [(name, rows) for name, rows in sections if rows]
    result['file_size'] = f'{size / 1024 / 1024:.2f} MB' if size >= 1024 * 1024 else f'{size / 1024:.1f} KB'
    return result
