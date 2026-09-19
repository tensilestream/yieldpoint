"""An exclusive lock between processes, for appending to a shared file.

A thread lock cannot do this, and append mode cannot either. POSIX makes an
``O_APPEND`` write atomic only up to the pipe buffer; Windows implements append
as seek-to-end-then-write, which is two operations. Two processes that seek to
the same end offset both write there, and one silently overwrites the other.

**No error is raised when that happens**, which is what makes it dangerous: the
write returns successfully, ``record`` reports ``True``, and the line is gone.
A retry loop cannot help, because there is nothing to retry on. The only fix is
to stop the second writer entering at all.

The lock is taken on a sidecar ``<name>.lock`` file rather than on the data file
itself, so acquiring it never depends on the data file's handle state or on the
mode it happens to be open in. The sidecar lives beside the ledger inside the
self-ignoring state directory, so it is never committed.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

if os.name == "nt":
    import msvcrt

    #: ``LK_LOCK`` retries for about ten seconds before raising, which is the
    #: blocking behaviour ``flock`` gives for free. One byte at offset zero is
    #: locked; the region need not exist, and nothing ever reads it.
    def _take(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _drop(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _take(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _drop(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def exclusive(target: Path | str):
    """Hold the cross-process lock guarding appends to ``target``."""
    fd = os.open(str(target) + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _take(fd)
        try:
            yield
        finally:
            _drop(fd)
    finally:
        os.close(fd)


__all__ = ["exclusive"]
