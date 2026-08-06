"""Cross-platform advisory whole-file locking for same-host coordination.

fcntl.flock (POSIX) and msvcrt.locking (Windows) differ in shape: flock takes
a real shared/exclusive lock on the whole file and blocks until acquired,
while msvcrt only locks byte ranges, has no shared mode, and only offers a
non-blocking primitive. Every caller here locks byte 0 of a stream it holds
for the duration of a critical section, so the Windows lock always targets
that byte and a "shared" lock is implemented as exclusive: readers still get
correct data, they just serialize against each other instead of overlapping.
"""

from __future__ import annotations

import errno
import os
import time
from typing import IO

_POLL_SECONDS = 0.01


def _is_windows_lock_contention(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
        error,
        "winerror",
        None,
    ) in {32, 33}


def _lock_windows_blocking(stream: IO) -> None:
    import msvcrt

    stream.seek(0)
    while True:
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if not _is_windows_lock_contention(exc):
                raise
            time.sleep(_POLL_SECONDS)


def lock_exclusive(stream: IO) -> None:
    """Block until an exclusive advisory lock on ``stream`` is held."""
    if os.name == "nt":
        _lock_windows_blocking(stream)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)


def lock_shared(stream: IO) -> None:
    """Block until a shared advisory lock on ``stream`` is held.

    Windows has no shared-lock primitive available here, so this blocks for
    an exclusive lock instead; see the module docstring for why that is safe.
    """
    if os.name == "nt":
        _lock_windows_blocking(stream)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)


def unlock(stream: IO) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
