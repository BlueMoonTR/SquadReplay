"""agent/memory_backend.py — Linux process-memory backend, pymem-compatible.

Reads/writes another process's memory via process_vm_readv/writev (ctypes
against libc) behind a Pymem-shaped API, so the rest of the codebase can
call self.pm.read_bytes(...) without the real (Windows-only) pymem package.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from pathlib import Path

logger = logging.getLogger("squad_agent.backend.linux")


class MemoryReadError(Exception):
    """Raised on any read failure: unmapped address, dead process,
    or ``process_vm_readv`` returning short / EFAULT / EPERM."""


# pymem-shaped exception module so ``pymem.exception.MemoryReadError``
# references in the reader keep resolving.
class _exception_module:  # noqa: N801 — naming mirrors pymem.exception
    MemoryReadError = MemoryReadError


exception = _exception_module()

# ---------------------------------------------------------------------------
# libc / process_vm_readv binding
# ---------------------------------------------------------------------------
_libc_path = ctypes.util.find_library("c") or "libc.so.6"
_libc = ctypes.CDLL(_libc_path, use_errno=True)


class _IoVec(ctypes.Structure):
    _fields_ = (
        ("iov_base", ctypes.c_void_p),
        ("iov_len",  ctypes.c_size_t),
    )


try:
    _process_vm_readv = _libc.process_vm_readv
    _process_vm_readv.argtypes = (
        ctypes.c_int,                  # pid
        ctypes.POINTER(_IoVec),        # local iov
        ctypes.c_ulong,                # liovcnt
        ctypes.POINTER(_IoVec),        # remote iov
        ctypes.c_ulong,                # riovcnt
        ctypes.c_ulong,                # flags (always 0)
    )
    _process_vm_readv.restype = ctypes.c_ssize_t
    _HAVE_PVR = True
except AttributeError:
    _process_vm_readv = None
    _HAVE_PVR = False
    logger.warning("data channel unavailable; using fallback path")

try:
    _process_vm_writev = _libc.process_vm_writev
    _process_vm_writev.argtypes = (
        ctypes.c_int,
        ctypes.POINTER(_IoVec),
        ctypes.c_ulong,
        ctypes.POINTER(_IoVec),
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
    _process_vm_writev.restype = ctypes.c_ssize_t
    _HAVE_PVW = True
except AttributeError:
    _process_vm_writev = None
    _HAVE_PVW = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_image(image: str | None) -> str:
    """Strip a legacy .exe suffix so callers can pass either spelling."""
    if not image:
        return "SquadGameServer"
    n = image.strip()
    if n.lower().endswith(".exe"):
        n = n[:-4]
    return n


def _find_pid_for_image(image: str) -> int | None:
    """Walk /proc and match comm (kernel-truncated to 15 chars) or the
    binary path. Returns the lowest-numbered matching PID."""
    target = _normalize_image(image)
    target_lc = target.lower()
    # TASK_COMM_LEN=16 (15+NUL) truncates comm; compare via prefix.
    target_comm = target_lc[:15]
    candidates: list[int] = []
    try:
        for entry in Path("/proc").iterdir():
            name = entry.name
            if not name.isdigit():
                continue
            pid = int(name)
            # Prefer exe path; fall back to comm if exe is unreadable.
            exe_match = False
            try:
                exe = os.readlink(entry / "exe")
                if target_lc in exe.lower():
                    exe_match = True
            except OSError:
                pass
            comm_match = False
            if not exe_match:
                try:
                    comm = (entry / "comm").read_text().strip().lower()
                    if comm == target_lc or comm == target_comm:
                        comm_match = True
                except OSError:
                    continue
            if exe_match or comm_match:
                candidates.append(pid)
    except OSError as exc:
        logger.warning("failed to scan /proc: %s", exc)
        return None
    return min(candidates) if candidates else None


def _resolve_base_address(pid: int, image: str) -> int:
    """Pick the binary's base address from /proc/<pid>/maps: the FIRST
    mapping for the binary (file offset 0), not the later .text/r-xp
    mapping — picking the executable mapping by accident would skew
    every offset by tens of MB. Falls back to the first executable
    mapping if the binary path is hidden."""
    target = _normalize_image(image).lower()
    first_for_target: int | None = None
    try:
        with open(f"/proc/{pid}/maps", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split(maxsplit=5)
                if len(parts) < 6:
                    continue
                addr_range, _perms, _off, _dev, _inode, path = parts
                base = path.strip().rsplit("/", 1)[-1].lower()
                if not base:
                    continue
                if base == target or base.startswith(target):
                    first_for_target = int(addr_range.split("-")[0], 16)
                    break
    except OSError as exc:
        raise OSError(f"cannot read /proc/{pid}/maps: {exc}") from exc
    if first_for_target is not None:
        return first_for_target
    # Fallback: first executable mapping (path sometimes hidden).
    try:
        with open(f"/proc/{pid}/maps", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                if "x" in parts[1]:
                    return int(parts[0].split("-")[0], 16)
    except OSError:
        pass
    return 0


# ---------------------------------------------------------------------------
# Pymem-shaped class for Linux
# ---------------------------------------------------------------------------
class Pymem:
    """Linux equivalent of ``pymem.Pymem`` — same constructor +
    attribute names so the reader's call sites work unchanged."""

    def __init__(self, image: str | None = None) -> None:
        self.process_id: int | None = None
        self.process_handle = None    # parity with pymem
        self.base_address: int = 0
        self._image: str = _normalize_image(image)
        if image:
            pid = _find_pid_for_image(self._image)
            if not pid:
                raise OSError(
                    f"process not found: {self._image} (no /proc match)"
                )
            self.open_process_from_id(pid)

    def open_process_from_id(self, pid: int) -> None:
        pid = int(pid)
        # Just check the directory exists; a readv smoke-test would be racy.
        if not Path(f"/proc/{pid}").is_dir():
            raise OSError(f"no such pid: {pid}")
        self.process_id = pid
        self.process_handle = pid  # same int — used as handle by callers
        self.base_address = _resolve_base_address(pid, self._image)

    def read_bytes(self, address: int, size: int) -> bytes:
        if self.process_id is None:
            raise MemoryReadError("not attached to a process")
        if size <= 0:
            return b""
        if _HAVE_PVR:
            buf = (ctypes.c_char * size)()
            local = _IoVec(ctypes.cast(buf, ctypes.c_void_p), size)
            remote = _IoVec(ctypes.c_void_p(address), size)
            n = _process_vm_readv(
                self.process_id,
                ctypes.byref(local), 1,
                ctypes.byref(remote), 1,
                0,
            )
            if n == size:
                return bytes(buf)
            err = ctypes.get_errno()
            raise MemoryReadError(
                f"process_vm_readv({size}@0x{address:x}) -> n={n} "
                f"errno={err} ({os.strerror(err) if err else 'short read'})"
            )
        # /proc/<pid>/mem fallback — needs same-UID + ptrace_scope=0 or root.
        try:
            with open(f"/proc/{self.process_id}/mem", "rb", buffering=0) as f:
                f.seek(address)
                data = f.read(size)
        except OSError as exc:
            raise MemoryReadError(
                f"/proc/{self.process_id}/mem read({size}@0x{address:x}) "
                f"failed: {exc}"
            ) from exc
        if len(data) != size:
            raise MemoryReadError(
                f"/proc/{self.process_id}/mem short read "
                f"({size}@0x{address:x}) got {len(data)}"
            )
        return data

    def write_bytes(self, address: int, data: bytes, length: int) -> None:
        """Write ``length`` bytes from ``data`` into the remote process via
        process_vm_writev (needs ptrace_scope=0 or CAP_SYS_PTRACE), falling
        back to /proc/<pid>/mem. Raises MemoryReadError on failure."""
        if self.process_id is None:
            raise MemoryReadError("not attached to a process")
        to_write = data[:length]
        size = len(to_write)
        if size == 0:
            return
        if _HAVE_PVW:
            buf = (ctypes.c_char * size)(*to_write)
            local = _IoVec(ctypes.cast(buf, ctypes.c_void_p), size)
            remote = _IoVec(ctypes.c_void_p(address), size)
            n = _process_vm_writev(
                self.process_id,
                ctypes.byref(local), 1,
                ctypes.byref(remote), 1,
                0,
            )
            if n == size:
                return
            err = ctypes.get_errno()
            raise MemoryReadError(
                f"process_vm_writev({size}@0x{address:x}) -> n={n} "
                f"errno={err} ({os.strerror(err) if err else 'short write'})"
            )
        # /proc/<pid>/mem fallback
        try:
            with open(f"/proc/{self.process_id}/mem", "r+b", buffering=0) as f:
                f.seek(address)
                written = f.write(to_write)
        except OSError as exc:
            raise MemoryReadError(
                f"/proc/{self.process_id}/mem write({size}@0x{address:x}) "
                f"failed: {exc}"
            ) from exc
        if written != size:
            raise MemoryReadError(
                f"/proc/{self.process_id}/mem short write "
                f"({size}@0x{address:x}) wrote {written}"
            )
