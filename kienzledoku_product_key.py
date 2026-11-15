"""Read the private compiled manufacturer key, never from public source/config."""
import ctypes
import json
import sys
from pathlib import Path


def production_build(root=None):
    marker = Path(root or Path(__file__).parent) / 'release.json'
    if not marker.exists():
        return False
    return json.loads(marker.read_text()).get('manufacturer_key') == 'production'


def embedded_api_key(root=None):
    root = Path(root or Path(__file__).parent)
    if not production_build(root):
        return None
    try:
        name = {'darwin':'libkienzledoku_product.dylib','win32':'kienzledoku_product.dll'}.get(sys.platform,'libkienzledoku_product.so')
        library = ctypes.CDLL(str(root / name))
        copy_key = library.kienzledoku_copy_product_key
        copy_key.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        copy_key.restype = ctypes.c_size_t
        buffer = ctypes.create_string_buffer(1024)
        try:
            length = copy_key(buffer, len(buffer))
            if not 16 <= length < len(buffer):
                raise ValueError()
            key = buffer.raw[:length].decode('ascii')
            if any(c.isspace() for c in key):
                raise ValueError()
            return key, 'Eingebetteter KienzleDoku-Hersteller-Key'
        finally:
            ctypes.memset(buffer, 0, len(buffer))
    except Exception:
        raise RuntimeError('Der eingebettete Hersteller-Key konnte nicht geladen werden. Bitte Kienzledoku erneut installieren.') from None
