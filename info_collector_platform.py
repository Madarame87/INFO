"""Small cross-platform helpers shared by the native host and local flows."""

import errno
import os
from pathlib import Path


_WINDOWS_LOCK_ERRORS = {33, 36}


def user_home():
    """Return the real user home, with an explicit override for isolated tests."""
    override = os.environ.get("INFO_COLLECTOR_HOME")
    return Path(override).expanduser().resolve() if override else Path.home()


def _prepare_lock_file(fd):
    if os.fstat(fd).st_size == 0:
        os.write(fd, b"\0")
        os.fsync(fd)
    os.lseek(fd, 0, os.SEEK_SET)


def _lock_nonblocking(fd):
    _prepare_lock_file(fd)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _is_busy_error(exc):
    return (
        exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
        or getattr(exc, "winerror", None) in _WINDOWS_LOCK_ERRORS
    )


def acquire_lock(path):
    """Acquire a one-byte exclusive lock without blocking; return its fd or None."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _lock_nonblocking(fd)
        return fd
    except OSError as exc:
        os.close(fd)
        if _is_busy_error(exc):
            return None
        raise


def release_lock(fd):
    """Release and close a descriptor returned by acquire_lock."""
    if fd is None:
        return
    try:
        _unlock(fd)
    finally:
        os.close(fd)


def lock_is_held(path):
    """Probe whether another process currently owns the lock file."""
    path = Path(path)
    if not path.is_file():
        return False
    fd = acquire_lock(path)
    if fd is None:
        return True
    release_lock(fd)
    return False

