"""Cross-process update/recording exclusion; contains no patient state."""
import os
from pathlib import Path
import sys


class Lease:
    def __init__(self,path,exclusive=False):
        self.handle=None;self.fd=None;path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if path.is_symlink():raise RuntimeError('Unsichere Updatesperre.')
        if sys.platform=='win32':
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
            kernel.CreateFileW.restype=wintypes.HANDLE
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            # Shared readers exclude the installer's read/write exclusive handle.
            h=kernel.CreateFileW(str(path),0xC0000000 if exclusive else 0x80000000,0 if exclusive else 1,None,4,0x80,None)
            if h==ctypes.c_void_p(-1).value:raise RuntimeError('Kienzledoku wird aktualisiert oder ist noch geöffnet. Bitte zuerst den anderen Vorgang abschließen.')
            self.handle=h;self.kernel=kernel
        else:
            import fcntl
            self.fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            try:fcntl.flock(self.fd,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
            except OSError:
                os.close(self.fd);self.fd=None
                raise RuntimeError('Kienzledoku wird aktualisiert oder ist noch geöffnet. Bitte zuerst den anderen Vorgang abschließen.') from None
    def close(self):
        if self.handle is not None:self.kernel.CloseHandle(self.handle);self.handle=None
        if self.fd is not None:os.close(self.fd);self.fd=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
