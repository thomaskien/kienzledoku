"""Private build-time obfuscation. This impedes strings, not reverse engineering.

Only the generated binaries may leave the private temporary directory. Neither
the original key nor the generated masked source belongs in a public repository.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile


def read_key(path):
    try:
        raw = Path(path).read_bytes()
        key = raw.strip()
        if len(raw) > 1024 or not 16 <= len(key) <= 512 or any(c < 33 or c > 126 for c in key):
            raise ValueError()
        return key
    except Exception:
        raise ValueError('Private Hersteller-Key-Datei fehlt oder hat ein ungültiges Format.') from None


def private_write(path, text):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        f.write(text)


class ProductKeyBuild:
    def __init__(self, key_file, root):
        self.key = read_key(key_file)
        self.root = Path(root)

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kienzledoku-private-build-', dir='/private/tmp')
        self.path = Path(self.temp.name)
        # Independent random shares for the two consumers. Volatile C data and
        # Go mutable globals keep the compiler from folding a plaintext string.
        def shares():
            mask = secrets.token_bytes(len(self.key))
            return ','.join(map(str, mask)), ','.join(str(a ^ b) for a, b in zip(mask, self.key))
        mask, cipher = shares()
        self.c_source = self.path/'product.c'
        private_write(self.c_source, '''#include <stddef.h>
static const volatile unsigned char a[] = {%s};
static const volatile unsigned char b[] = {%s};
#ifdef _WIN32
__declspec(dllexport) __attribute__((noinline))
#else
__attribute__((visibility("default"), noinline))
#endif
size_t kienzledoku_copy_product_key(unsigned char *out, size_t capacity) {
    if (!out || capacity <= sizeof(a)) return 0;
    for (size_t i=0; i<sizeof(a); ++i) out[i] = a[i] ^ b[i];
    out[sizeof(a)] = 0;
    return sizeof(a);
}
''' % (mask, cipher))
        mask, cipher = shares()
        go_source = self.path/'api_key.go'
        private_write(go_source, '''package main
var productShareA = []byte{%s}
var productShareB = []byte{%s}
//go:noinline
func embeddedAPIKey() string {
    out := make([]byte, len(productShareA))
    for i := range out { out[i] = productShareA[i] ^ productShareB[i] }
    return string(out)
}
''' % (mask, cipher))
        self.overlay = self.path/'overlay.json'
        private_write(self.overlay, json.dumps({'Replace': {str(self.root/'connect/api_key.go'): str(go_source)}}))
        return self

    def __exit__(self, *_):
        self.temp.cleanup()
        self.key = b''

    def check_file(self, path):
        # Also reject the most common plain encodings, not only raw ASCII.
        forms = (self.key, self.key.decode().encode('utf-16le'), self.key.decode().encode('utf-16be'),
                 base64.b64encode(self.key), self.key.hex().encode(), self.key.hex().upper().encode())
        overlap = max(map(len, forms)) - 1
        tail = b''
        with Path(path).open('rb') as stream:
            while block := stream.read(1024*1024):
                block = tail + block
                if any(form in block for form in forms):
                    raise RuntimeError('Build abgebrochen: Klartext-Hersteller-Key in einer Ausgabedatei erkannt.')
                tail = block[-overlap:]

    def check_tree(self, root):
        for path in Path(root).rglob('*'):
            if path.is_file() and not path.is_symlink():
                self.check_file(path)

    def run(self, argv, **kwargs):
        result = subprocess.run([str(x) for x in argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        if result.returncode:
            raise RuntimeError('Privater Build-Schritt fehlgeschlagen: '+Path(str(argv[0])).name+' (Exit '+str(result.returncode)+'). Keine privaten Build-Ausgaben veröffentlicht.')
        return result
