"""Keep local account state private to the current user."""
from contextlib import contextmanager
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile


class StoreError(Exception):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name == "posix" and sys.platform.startswith("linux"):
        # Linux relies on a private state directory and 0600 files. A key kept
        # beside the data would not provide stronger protection for a timer.
        return data
    if os.name != "nt":
        raise StoreError("Local account storage requires Windows or Linux.")
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
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.directory.chmod(0o700)
            log = self.directory / "runs.jsonl"
            if log.exists():
                log.chmod(0o600)
            for path in self.directory.glob("*.bin"):
                if path.is_file() and not path.is_symlink():
                    path.chmod(0o600)

    def read(self, name: str, default=None):
        if (self.directory / "auth-transaction.bin").exists() and not getattr(self, "_locked", False):
            with self.lock():
                pass
        path = self.directory / f"{name}.bin"
        if not path.exists():
            return default
        try:
            return json.loads(_protect(path.read_bytes(), decrypt=True))
        except (ValueError, OSError) as exc:
            raise StoreError("Local account data could not be read.") from exc

    def write(self, name: str, value):
        encrypted = _protect(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        self._replace_bytes(name, encrypted)

    def _replace_bytes(self, name: str, data: bytes):
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f"{name}.bin")
            self._sync_directory()
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def transaction(self, *names: str):
        """Restore prior files after interruption, including the next process after a crash."""
        if not getattr(self, "_locked", False):
            raise StoreError("A transaction requires the account lock.")
        if (self.directory / "auth-transaction.bin").exists():
            raise StoreError("An earlier account change needs recovery.")
        previous = {}
        for name in names:
            if name not in ("profile", "order", "run_state"):
                raise StoreError("Unsupported account transaction file.")
            path = self.directory / f"{name}.bin"
            previous[name] = path.read_bytes() if path.exists() else None
        snapshot = {name: base64.b64encode(data).decode("ascii") if data is not None else None
                    for name, data in previous.items()}
        self._replace_bytes("auth-transaction", _protect(json.dumps(snapshot).encode("utf-8")))
        try:
            yield
        except BaseException:
            self._recover_transaction()
            raise
        else:
            (self.directory / "auth-transaction.bin").unlink()
            self._sync_directory()

    def _sync_directory(self):
        if os.name == "posix":
            fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _recover_transaction(self):
        journal = self.directory / "auth-transaction.bin"
        if not journal.exists():
            return
        try:
            snapshot = json.loads(_protect(journal.read_bytes(), decrypt=True))
            if not isinstance(snapshot, dict) or not set(snapshot).issubset({"profile", "order", "run_state"}):
                raise ValueError("Invalid account journal")
            for name, encoded in snapshot.items():
                path = self.directory / f"{name}.bin"
                if encoded is None:
                    path.unlink(missing_ok=True)
                else:
                    self._replace_bytes(name, base64.b64decode(encoded, validate=True))
            journal.unlink()
            self._sync_directory()
        except (ValueError, OSError, TypeError) as exc:
            raise StoreError("The interrupted account change could not be recovered.") from exc

    def append_log(self, line: str):
        fd = os.open(self.directory / "runs.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    @contextmanager
    def lock(self):
        with (self.directory / "run.lock").open("a+b") as stream:
            if os.name == "nt":
                import msvcrt
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
                    self._locked = True
                    self._recover_transaction()
                    yield
                finally:
                    self._locked = False
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            elif sys.platform.startswith("linux"):
                import fcntl
                stream.flush()
                os.fchmod(stream.fileno(), 0o600)
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise StoreError("Another reservation command is running.") from exc
                try:
                    self._locked = True
                    self._recover_transaction()
                    yield
                finally:
                    self._locked = False
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            else:
                raise StoreError("This version supports Windows and Linux only.")
