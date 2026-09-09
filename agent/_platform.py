"""agent/_platform.py — /proc-based Linux helpers to locate and monitor
the SquadGameServer process (find_pid, is_pid_alive, list_processes_by_name)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("squad_agent.platform")

IS_LINUX = sys.platform.startswith("linux")


# ---------------------------------------------------------------------------
# Process discovery
# ---------------------------------------------------------------------------

def find_pid(image_name: str, executable_path: str | None = None,
             match_cmdline: str | None = None) -> int | None:
    """PID of a running process matching ``image_name``. ``executable_path``
    disambiguates multiple installs; ``match_cmdline`` disambiguates multiple
    instances of the same install (e.g. "-Port=7787"). Both must hold when
    supplied. Returns None if no match."""
    if IS_LINUX:
        return _find_pid_linux(image_name, executable_path, match_cmdline)
    raise NotImplementedError(f"find_pid: unsupported platform {sys.platform}")


def _find_pid_linux(image_name: str, executable_path: str | None,
                    match_cmdline: str | None = None) -> int | None:
    """Match /proc entries on comm + exe symlink + cmdline. comm is
    truncated to 15 chars by the kernel; .exe suffix is stripped so a
    Windows-named call site still matches the Linux binary."""
    target_comm = image_name
    if target_comm.endswith(".exe"):
        target_comm = target_comm[:-4]
    target_comm = target_comm[:15]  # kernel truncates comm to 16 bytes incl. NUL
    target_path = str(Path(executable_path).resolve()) if executable_path else None
    cmd_needle = (match_cmdline or "").strip() or None

    proc_root = Path("/proc")
    try:
        pid_dirs = [p for p in proc_root.iterdir() if p.name.isdigit()]
    except OSError as e:
        logger.warning("cannot read /proc: %s", e)
        return None

    # Phase 1: exact exe path match. Phase 2: inode match (container
    # bind-mounts show a different /proc/<pid>/exe text path for the same
    # file). Multiple inode matches with no cmd_needle -> ambiguous, None.

    exact_candidates: list[int] = []
    inode_candidates: list[int] = []

    # Resolve target inode once (avoid repeated stat inside the loop)
    tgt_ino: tuple[int, int] | None = None
    if target_path is not None:
        try:
            s = os.stat(target_path)
            tgt_ino = (s.st_ino, s.st_dev)
        except OSError:
            pass  # target doesn't exist; inode match impossible

    for pid_dir in pid_dirs:
        try:
            comm = (pid_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if comm != target_comm:
            continue

        if target_path is not None:
            try:
                exe_real = os.readlink(pid_dir / "exe")
            except OSError:
                continue

            if exe_real == target_path:
                exact_candidates.append(int(pid_dir.name))
            elif tgt_ino is not None:
                # Text-path mismatch — try inode match (Docker bind-mounts).
                try:
                    exe_st = os.stat(pid_dir / "exe")
                    if (exe_st.st_ino, exe_st.st_dev) == tgt_ino:
                        inode_candidates.append(int(pid_dir.name))
                except OSError:
                    pass
        else:
            # No target_path configured — accept any process with matching comm.
            exact_candidates.append(int(pid_dir.name))

    # Prefer exact matches; fall back to inode matches.
    candidates = exact_candidates if exact_candidates else inode_candidates

    # Apply optional cmdline filter.
    if cmd_needle is not None:
        filtered: list[int] = []
        for pid in candidates:
            try:
                raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
            except OSError:
                continue
            cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
            if cmd_needle in cmdline:
                filtered.append(pid)
        candidates = filtered

    if not candidates:
        return None

    if len(candidates) > 1 and not inode_candidates:
        # Multiple exact matches — unusual but return first silently.
        return candidates[0]

    if len(candidates) > 1 and inode_candidates:
        # Ambiguous inode matches, no match_cmdline to disambiguate — warn.
        pids_str = ", ".join(str(p) for p in candidates)
        logger.warning(
            "Multiple service instances share the same binary "
            "(%s — PIDs %s). Add \"match_cmdline\" to "
            "squad_replay_config.json (e.g. \"Port=7787\") to "
            "select the right instance.",
            target_path,
            pids_str,
        )
        return None

    return candidates[0]


# ---------------------------------------------------------------------------
# PID liveness
# ---------------------------------------------------------------------------

def is_pid_alive(pid: int | None) -> bool:
    """True when ``pid`` maps to a running process on this host."""
    if not pid or pid <= 0:
        return False
    if IS_LINUX:
        return _is_pid_alive_linux(pid)
    raise NotImplementedError(f"is_pid_alive: unsupported platform {sys.platform}")


def _is_pid_alive_linux(pid: int) -> bool:
    """``os.kill(pid, 0)`` — signal 0 is a no-op probe; raises
    ProcessLookupError if the PID doesn't exist, PermissionError if
    we lack access (still means the process is alive)."""
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Orphan process cleanup (reader-side safeguard)
# ---------------------------------------------------------------------------

def list_processes_by_name(image_name: str) -> list[tuple[int, str]]:
    """(pid, command_line) pairs for every process matching ``image_name``.
    Used by the reader's orphan-killer. Command line is best-effort, empty
    string on /proc read failure; callers fall back to kill-by-pid."""
    if IS_LINUX:
        return _list_processes_linux(image_name)
    raise NotImplementedError(
        f"list_processes_by_name: unsupported platform {sys.platform}"
    )


def _list_processes_linux(image_name: str) -> list[tuple[int, str]]:
    target_comm = image_name[:-4] if image_name.endswith(".exe") else image_name
    target_comm = target_comm[:15]
    proc_root = Path("/proc")
    results: list[tuple[int, str]] = []
    try:
        entries = [p for p in proc_root.iterdir() if p.name.isdigit()]
    except OSError:
        return results
    for pid_dir in entries:
        try:
            comm = (pid_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if comm != target_comm:
            continue
        try:
            cmdline = (pid_dir / "cmdline").read_bytes().decode("utf-8", errors="replace")
            # /proc exposes cmdline as NUL-separated argv. Humanify.
            cmdline = cmdline.replace("\x00", " ").strip()
        except OSError:
            cmdline = ""
        try:
            pid = int(pid_dir.name)
        except ValueError:
            continue
        results.append((pid, cmdline))
    return results


__all__ = [
    "IS_LINUX",
    "find_pid",
    "is_pid_alive",
    "list_processes_by_name",
]
