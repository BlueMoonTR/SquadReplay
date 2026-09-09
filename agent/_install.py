"""agent/_install.py — Linux self-install bootstrap.

Triggered by `./SquadReplay --install [--enroll <token>]` run as root:
detects the Squad process, picks the service user, writes sysctl/caps/
start.sh/config, and hands off enrollment. Operator runs the agent
themselves via ./start.sh (no systemd unit is installed).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("SquadReplay.install")


# ---------------------------------------------------------------------------
# Terminal colour helpers
# ---------------------------------------------------------------------------

def _ansi(code: str, text: str) -> str:
    """Wrap text in an ANSI escape sequence, but only when stdout is a TTY."""
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

def _green(t: str)  -> str: return _ansi("1;92", t)
def _red(t: str)    -> str: return _ansi("1;91", t)
def _yellow(t: str) -> str: return _ansi("1;93", t)
def _bold(t: str)   -> str: return _ansi("1",    t)
def _dim(t: str)    -> str: return _ansi("2",    t)


# Keyword → operator hint mapping. First matching entry wins.
_INSTALL_HINTS: list[tuple[str, str]] = [
    ("must run as root",
     "Run:  sudo ./SquadReplay --install --enroll <token>"),
    ("no running",
     "Start the Squad dedicated server first, then re-run the installer."),
    ("multiple SquadGameServer",
     "Pass --force-user <username> to specify which user to run under."),
    ("timed out",
     "Token may be expired. Ask your platform operator for a new one."),
    ("expired",
     "Ask your platform operator for a new enrollment token."),
    ("enrollment failed",
     "Check network connectivity to central, then retry."),
    ("setpriv",
     "Make sure the 'util-linux' package is installed:\n"
     "    sudo apt-get install util-linux"),
]


def _print_success_banner(workdir: Path) -> None:
    w = 50
    bar = "═" * w
    print()
    print(_green(f"╔{bar}╗"))
    print(_green("║") + _bold(_green(f"  ✓  INSTALLATION COMPLETE".center(w))) + _green("║"))
    print(_green(f"╚{bar}╝"))
    print()
    print(_bold("  Please start the agent with:"))
    print()
    print(f"    {_yellow('cd')} {workdir}")
    print(f"    {_yellow('./start.sh')}")
    print()
    print(_dim(f"  start.sh has its own restart loop, so the agent survives"))
    print(_dim(f"  crashes. It does NOT survive reboots — run a screen/tmux"))
    print(_dim(f"  session (or your own cron @reboot entry) if you want it"))
    print(_dim(f"  back up automatically after a reboot."))
    print()
    print(_dim(f"  Watch logs:"))
    print(_dim(f"    tail -f {workdir}/logs/agent.log"))
    print()


def _print_error_banner(exc: Exception) -> None:
    msg = str(exc)
    msg_lc = msg.lower()
    hint = next(
        (h for kw, h in _INSTALL_HINTS if kw.lower() in msg_lc),
        "Check the error message above and retry."
    )
    w = 50
    bar = "═" * w
    print()
    print(_red(f"╔{bar}╗"))
    print(_red("║") + _bold(_red("  ✗  INSTALLATION FAILED".center(w))) + _red("║"))
    print(_red(f"╚{bar}╝"))
    print()
    print(_red(f"  Error:  {msg}"))
    print()
    print(_bold("  Fix:"))
    for line in hint.splitlines():
        print(f"    {line}")
    print()


class InstallError(RuntimeError):
    """Raised when self-install hits an unrecoverable precondition;
    propagates to exit code 7."""


# Constants so a future refactor/test can override them.
_SYSCTL_PATH        = Path("/etc/sysctl.d/99-squad-replay.conf")
_DEFAULT_DEPLOY_REL = Path("BOTS") / "SquadReplay"      # under target user's $HOME


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def _ensure_root() -> None:
    """Install touches /etc/sysctl.d and needs setcap — must be root."""
    if os.geteuid() != 0:
        raise InstallError(
            "self-install must run as root (sudo). Re-run with "
            "`sudo ./SquadReplay --install [...]`"
        )


def _ensure_linux() -> None:
    if not sys.platform.startswith("linux"):
        raise InstallError(
            f"self-install supports Linux only (detected: {sys.platform})"
        )


# ---------------------------------------------------------------------------
# Squad process discovery
# ---------------------------------------------------------------------------

# Squad server binary name on Linux. Multiple matches -> lowest PID wins.
_SQUAD_COMM = "SquadGameServer"


def _detect_squad_user_and_path() -> tuple[str, str]:
    """Scan /proc for a running SquadGameServer process; return
    (user, executable_path). Raises InstallError on zero or ambiguous
    matches — we attach to an existing user, never guess one."""
    candidates: list[tuple[int, str, str]] = []   # (pid, user, exe_path)
    proc_root = Path("/proc")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if comm != _SQUAD_COMM:
            continue
        # exe symlink is visible from the host PID namespace even in a container.
        try:
            exe_path = os.readlink(entry / "exe")
        except OSError:
            continue
        # /proc/<pid>/status -> Uid: real effective saved fsuid
        try:
            uid_line = next(
                ln for ln in (entry / "status").read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
                if ln.startswith("Uid:")
            )
            real_uid = int(uid_line.split()[1])
        except (OSError, StopIteration, ValueError, IndexError):
            continue
        # Skip root-owned Squad processes — running the agent as root is a footgun.
        if real_uid == 0:
            continue
        import pwd
        try:
            user = pwd.getpwuid(real_uid).pw_name
        except KeyError:
            continue
        candidates.append((int(entry.name), user, exe_path))

    if not candidates:
        raise InstallError(
            f"no running '{_SQUAD_COMM}' process found. Start the Squad "
            "dedicated server first, then re-run the installer."
        )
    if len({c[1] for c in candidates}) > 1:
        users = sorted({c[1] for c in candidates})
        raise InstallError(
            f"multiple SquadGameServer processes under different users "
            f"({', '.join(users)}). Pass --force-user <name> to pick one."
        )
    # Deterministic pick: lowest PID among same-user candidates.
    candidates.sort()
    pid, user, exe_path = candidates[0]
    logger.info("[install] service detected: user=%s", user)
    return user, exe_path


# ---------------------------------------------------------------------------
# Sysctl drop-in
# ---------------------------------------------------------------------------

_SYSCTL_BODY = """\
# SquadReplay agent runtime requirement. Generated by `SquadReplay --install`.
# Safe to remove after uninstall; harmless to leave in place.
kernel.yama.ptrace_scope = 0
"""


def _write_sysctl_dropin() -> None:
    _SYSCTL_PATH.write_text(_SYSCTL_BODY, encoding="utf-8")
    _SYSCTL_PATH.chmod(0o644)
    # Apply immediately so the current host doesn't require a reboot.
    try:
        subprocess.run(
            ["sysctl", "--load", str(_SYSCTL_PATH)],
            check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # Recoverable — file is on disk; next reboot picks it up.
        logger.warning("sysctl --load failed (%s); reboot will apply on next boot", exc)
    logger.info("wrote %s", _SYSCTL_PATH)


# ---------------------------------------------------------------------------
# Deploy directory + binary placement
# ---------------------------------------------------------------------------

def _resolve_deploy_dir(user: str, override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    # Prefer the dir the binary is already running from, so a second
    # install doesn't collide with an existing one.
    onefile_dir = os.environ.get('NUITKA_ONEFILE_DIRECTORY', '')
    if onefile_dir:
        p = Path(onefile_dir).resolve()
        if p.is_dir():
            return p
    import pwd
    home = Path(pwd.getpwnam(user).pw_dir)
    return (home / _DEFAULT_DEPLOY_REL).resolve()


def _self_copy_to_deploy(deploy_dir: Path) -> Path:
    """Copy the running binary into deploy_dir. No-op if already there.
    Returns the destination path."""
    # Nuitka onefile: sys.executable points at the temp-extracted runtime,
    # not the original ELF — use NUITKA_ONEFILE_DIRECTORY instead.
    onefile_dir = os.environ.get('NUITKA_ONEFILE_DIRECTORY', '')
    if onefile_dir:
        current = (Path(onefile_dir) / 'SquadReplay').resolve()
    else:
        current = Path(sys.executable).resolve()
    target = (deploy_dir / "SquadReplay").resolve()
    if current == target:
        return target
    deploy_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current, target)
    target.chmod(0o755)
    logger.info("copied binary to %s", target)
    return target


_START_SH_BODY = """\
#!/usr/bin/env bash
# Squad Replay agent — start/restart-loop wrapper.
# Generated by `SquadReplay --install`. Idempotent; safe to re-run.
# This is the primary way to run the agent (no systemd unit is installed) —
# survives crashes via the loop below, but NOT reboots. Re-run this script
# after a reboot (e.g. from a screen/tmux session, or your own cron @reboot
# entry) if you want it back up automatically.
set -euo pipefail
cd "$(dirname "$0")"
# Enrollment computed this host's HW fingerprint as {user} (the service
# user, via setpriv — see _run_enroll_as_user). Root can additionally read
# /sys/class/dmi/id/product_uuid, which {user} cannot, so root and {user}
# hash to DIFFERENT fingerprints on the same machine and the binding check
# in squad_memory_reader.py would reject root-started runs. Re-exec as
# {user} so an operator who is root on the docker host (the common case)
# still lands on the enrolled UID.
if [ "$(id -un)" = "root" ]; then
    exec setpriv --reuid {user} --regid {user} --init-groups --no-new-privs "$(pwd)/$(basename "$0")" "$@"
fi

if [ -f .env.agent ]; then
    set -a; . .env.agent; set +a
fi

# Tells the auto-update swap helper (agent/updater.py) that WE own
# restarting the binary after a self-update self-replace exit — it must
# not also relaunch, or two readers would race PTRACE_ATTACH on the game
# process.
export SQUAD_AGENT_SUPERVISED=1

mkdir -p logs

# Supervisor-level messages (launch/restart/stale-kill) go straight into
# the same rotating log the reader itself writes (logs/agent.log) instead
# of a separate service.log — one file, one rotation policy (daily,
# 7-day FIFO — see squad_memory_reader.py's TimedRotatingFileHandler).
# `|| true` so a stale/unwritable log file never takes the launcher down.
_log() {{
    echo "$1"
    echo "$1" >> logs/agent.log 2>/dev/null || true
}}

_self=$$
_stale=$(pgrep -f "$(pwd)/SquadReplay" 2>/dev/null | grep -v "^$_self$" || true)
if [ -n "$_stale" ]; then
    _log "=== stale process(es) detected: $_stale — sending SIGTERM ==="
    kill $_stale 2>/dev/null || true
    # Wait up to 10s for a graceful exit before escalating. A lingering
    # writer here would violate live_data_mmap.py's single-writer seqlock
    # invariant if the new instance starts while the old one still has the
    # mmap open — two writers tearing each other's snapshots mid-write.
    for _i in $(seq 1 20); do
        _stale=$(pgrep -f "$(pwd)/SquadReplay" 2>/dev/null | grep -v "^$_self$" || true)
        [ -z "$_stale" ] && break
        sleep 0.5
    done
    if [ -n "$_stale" ]; then
        _log "=== $_stale still alive after 10s, sending SIGKILL ==="
        kill -9 $_stale 2>/dev/null || true
        sleep 1
    fi
fi

# Exit codes that won't fix themselves by restarting (see
# squad_memory_reader.py ~line 10500-10575): 2/5 = packaged binary missing
# the agent/ package (needs rebuild), 4 = central sent an unrecognised
# offset bundle (schema mismatch), 6 = HW fingerprint binding mismatch
# (needs re-enroll). Retrying these every 5s just spams the log; back off
# so a human has time to read the actionable message the agent already
# logged above.
_PERMANENT_RC=" 2 4 5 6 "

# set -e must be off for the restart loop — a non-zero agent exit propagates
# through the pipe and kills the script, defeating the restart entirely.
set +e
while true; do
    _log "=== launching SquadReplay $(date) ==="
    ./SquadReplay "$@"
    _rc=$?
    case "$_PERMANENT_RC" in
        *" $_rc "*)
            _log "=== agent exited rc=$_rc at $(date) — config/binding issue, see message above; backing off 300s instead of hammering ==="
            sleep 300
            ;;
        *)
            _log "=== agent exited rc=$_rc at $(date); restarting in 5s ==="
            sleep 5
            ;;
    esac
done
"""


def _write_start_sh(workdir: Path, user: str) -> None:
    sh = workdir / "start.sh"
    if sh.exists():
        return
    sh.write_text(_START_SH_BODY.format(user=user), encoding="utf-8")
    sh.chmod(0o755)
    _chown_recursive(sh, user)
    logger.info("wrote %s", sh)


def _chown_recursive(path: Path, user: str) -> None:
    import pwd
    pw = pwd.getpwnam(user)
    os.chown(path, pw.pw_uid, pw.pw_gid)
    if path.is_dir():
        for child in path.rglob("*"):
            try:
                os.chown(child, pw.pw_uid, pw.pw_gid)
            except OSError:
                pass


def _apply_caps(binary_path: Path) -> None:
    """Belt-and-braces: file caps keep ptrace working even if a future
    operator flips kernel.yama.ptrace_scope back to 1."""
    try:
        subprocess.run(
            ["setcap", "cap_sys_ptrace,cap_dac_read_search+eip", str(binary_path)],
            check=True, capture_output=True, text=True,
        )
        logger.info("applied file capabilities to %s", binary_path)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # Not fatal — the sysctl drop-in is the primary mechanism.
        logger.warning("setcap failed (%s); falling back to sysctl tunable", exc)


# ---------------------------------------------------------------------------
# Enrollment hand-off
# ---------------------------------------------------------------------------

_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,32}$")


def _run_enroll_as_user(user: str, deploy_dir: Path, binary: Path, token: str) -> None:
    """Drop privileges to ``user`` via setpriv and invoke --enroll;
    writes .env.agent next to the binary as that user."""
    if not _USERNAME_RE.match(user):
        raise InstallError(f"refusing to enroll under suspicious user name {user!r}")
    # --enroll-only exits right after writing .env.agent; without it the
    # subprocess keeps running and subprocess.run blocks until timeout.
    try:
        subprocess.run(
            [
                "setpriv", "--reuid", user, "--regid", user, "--init-groups",
                str(binary), "--enroll", token, "--enroll-only",
            ],
            cwd=str(deploy_dir),
            check=True,
            timeout=120,
        )
        logger.info("enrollment complete (.env.agent written under %s)", deploy_dir)
    except subprocess.TimeoutExpired:
        raise InstallError(
            "enrollment timed out after 120s — token may be expired or "
            "central unreachable. Generate a new token and retry."
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise InstallError(f"enrollment failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

def install_linux(
    *,
    enroll_token: str | None = None,
    deploy_dir: Path | None = None,
    force_user: str | None = None,
) -> int:
    """Run the full Linux self-install. Returns 0 or raises InstallError.
    Idempotent (safe as a repair step) — overwrites the sysctl file and
    start.sh. No systemd unit is installed; run via ./start.sh."""
    _ensure_linux()
    _ensure_root()

    # 1. Discover Squad's service user (we won't run agent as root).
    if force_user:
        if not _USERNAME_RE.match(force_user):
            raise InstallError(f"invalid --force-user value {force_user!r}")
        # Trust operator override; still grab exe_path via process scan.
        _, exe_path = _detect_squad_user_and_path()
        target_user = force_user
    else:
        target_user, exe_path = _detect_squad_user_and_path()
    logger.info("target service user: %s", target_user)

    # 2. Place binary into deploy dir under target user's home.
    workdir = _resolve_deploy_dir(target_user, deploy_dir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "logs").mkdir(exist_ok=True)
    (workdir / "replays").mkdir(exist_ok=True)
    binary = _self_copy_to_deploy(workdir)
    _write_start_sh(workdir, target_user)
    _chown_recursive(workdir, target_user)

    # 3. Apply ptrace permissions (primary: sysctl drop-in; secondary: file caps).
    _write_sysctl_dropin()
    _apply_caps(binary)

    # 4. Write squad_replay_config.json for stable auto-PID attach.
    #    Prompt for a path if the auto-detected exe doesn't look like Squad.
    config_path = workdir / "squad_replay_config.json"
    if not config_path.exists():
        import json as _json
        _squad_binary_names = ("SquadGameServer", "Squad", "squadgame")
        _looks_like_squad = any(
            n.lower() in exe_path.lower() for n in _squad_binary_names
        )
        if not _looks_like_squad:
            print(
                f"\n[install] WARNING: detected executable does not look like "
                f"a Squad server binary:\n"
                f"  {exe_path}\n\n"
                f"Please enter the Squad dedicated server's install directory "
                f"(the one containing SquadGame/) — the SquadGame/Binaries/Linux/"
                f"SquadGameServer suffix is fixed and filled in automatically:\n"
                f"  /home/squad_server/SquadServer\n\n"
                f"A direct file or SquadGame/Binaries/Linux/ path also works.\n"
            )
            try:
                entered = input("[install] Squad server directory: ").strip()
            except (EOFError, KeyboardInterrupt):
                entered = ""
            # Accept either the server root or the Binaries/Linux/ dir directly.
            if entered:
                p = Path(entered)
                if p.is_dir():
                    for suffix in ("SquadGame/Binaries/Linux/SquadGameServer",
                                   "SquadGameServer"):
                        candidate = p / suffix
                        if candidate.is_file():
                            entered = str(candidate)
                            break
                p = Path(entered)
            if entered and Path(entered).is_file():
                exe_path = entered
                logger.info("using operator-supplied path: %s", exe_path)
            else:
                logger.warning(
                    "no valid path entered; using auto-detected path %s. "
                    "Edit squad_replay_config.json after install if needed.",
                    exe_path,
                )
        config_path.write_text(
            _json.dumps(
                {
                    "executable_path":      exe_path,
                    "process_name":         _SQUAD_COMM,
                    "attach_retry_seconds": 5,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        _chown_recursive(config_path, target_user)
        logger.info("wrote %s", config_path)

    # 5. Enrollment, only if a token was passed — otherwise start.sh runs
    #    but the agent refuses to push without secrets.
    if enroll_token:
        _run_enroll_as_user(target_user, workdir, binary, enroll_token)
    else:
        logger.info(
            "no --enroll token provided; .env.agent NOT created. "
            "Run `sudo -u %s %s --enroll <token>` later, then start "
            "the agent with `%s/start.sh`",
            target_user, binary, workdir,
        )

    _print_success_banner(workdir)
    return 0


__all__ = ["install_linux", "InstallError", "_print_error_banner"]
