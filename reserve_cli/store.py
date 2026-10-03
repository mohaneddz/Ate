"""Keep local credentials encrypted for the current Windows user using DPAPI."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile


class StoreError(Exception):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise StoreError("Encrypted storage requires Windows and the same Windows user that ran setup.")
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    api = ctypes.windll.crypt32
    function = api.CryptUnprotectData if decrypt else api.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise StoreError("Windows could not unlock the local encrypted data. Run setup as this user.")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.data)


class Store:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def read(self, name: str, default=None):
        path = self.directory / f"{name}.bin"
        if not path.exists():
            return default
        try:
            return json.loads(_protect(path.read_bytes(), decrypt=True))
        except (ValueError, OSError) as exc:
            raise StoreError("Local encrypted data could not be read.") from exc

    def write(self, name: str, value):
        encrypted = _protect(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f"{name}.bin")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def lock(self):
        if os.name != "nt":
            raise StoreError("This version supports Windows only.")
        import msvcrt
        with (self.directory / "run.lock").open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise StoreError("Another reservation command is running.") from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
