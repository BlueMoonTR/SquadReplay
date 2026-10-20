#!/usr/bin/env python3
"""SquadReplay agent -- one-file variant.

This single file IS the agent. Everything below the `#| ===== module:` lines
is the agent's source, kept as plain, readable, greppable text (each line
carries a `#| ` prefix so the file stays valid Python). The code at the top
is a small loader that serves those modules to the Python importer; it does
nothing else.

    python3 squadreplay_agent.py --bundle-info     what is in this file
    python3 squadreplay_agent.py --install --enroll <token>   (as root)

What this variant can and cannot do is a property of the code in this file,
not of a setting: see LEGAL.md and the README in the project repository.

Copyright (c) 2026 BlueMoonTR / the SquadReplay project.
Source-available, not open source: read it, run it unmodified on your own Squad
server. Modifying it to run, redistributing it, or extracting what the central
server delivers to it is not permitted. See LICENSE in the project repository.
"""
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import linecache
import os
import sys

# ---- filled in by the bundler -------------------------------------------------
_VARIANT = 'read-write-voice'
_VERSION = '0.87.2'
_BUILT_FROM = 'aff73536c462'
_SECTION_SHA256 = 'beb87eab671c77e532d1b2ca8dfcba78e4bcab57528a4a5a28ff2b6d04c5c5ed'
# -------------------------------------------------------------------------------

#: Every embedded module begins with a line that starts exactly like this.
MARK = "#| ===== "
PREFIX = "#| "


def _die(message):
    sys.stderr.write("squadreplay: %s\n" % message)
    sys.exit(2)


class _Module:
    __slots__ = ("name", "is_package", "lines")

    def __init__(self, name, is_package):
        self.name = name
        self.is_package = is_package
        self.lines = []

    @property
    def source(self):
        return "".join(self.lines)

    @property
    def relpath(self):
        parts = self.name.split(".")
        if self.is_package:
            return "/".join(parts + ["__init__.py"])
        return "/".join(parts) + ".py"


def read_embedded(path):
    """Parse the embedded modules back out of a bundle file.

    Returns ``({name: _Module}, sha256 of the embedded text)``. The text is
    exactly what the bundler wrote, so the hash can be compared with the one
    in the header.
    """
    modules = {}
    current = None
    section = hashlib.sha256()
    with open(path, encoding="utf-8", newline="") as fh:
        for raw in fh:
            if not raw.startswith("#|"):
                continue
            section.update(raw.encode("utf-8"))
            if raw.startswith(MARK):
                head = raw[len(MARK):].rstrip("\n").rstrip(" =")
                kind, _, name = head.partition(": ")
                if kind not in ("module", "package") or not name:
                    _die("damaged bundle: bad section line %r" % raw)
                current = _Module(name, kind == "package")
                modules[name] = current
            elif current is not None:
                if raw.startswith(PREFIX):
                    current.lines.append(raw[len(PREFIX):])
                else:                        # a bare "#|" is an empty source line
                    current.lines.append(raw[2:] if raw.strip() != "#|" else "\n")
    return modules, section.hexdigest()


class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves the embedded modules. Each keeps its own namespace, so the
    agent's `import agent.updater` and friends behave exactly as they do
    from a source checkout."""

    def __init__(self, modules, bundle_path):
        self._modules = modules
        self._dir = os.path.dirname(os.path.abspath(bundle_path))
        self._label = os.path.basename(bundle_path)

    def find_spec(self, fullname, path=None, target=None):
        mod = self._modules.get(fullname)
        if mod is None:
            return None
        return importlib.machinery.ModuleSpec(
            fullname, self, origin=self._origin(mod), is_package=mod.is_package)

    def _origin(self, mod):
        return "<%s: %s>" % (self._label, mod.relpath)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        mod = self._modules[module.__spec__.name]
        origin = self._origin(mod)
        source = mod.source
        # Where a checkout would keep this file. Code that finds "the
        # directory next to the agent" from __file__ keeps working.
        module.__file__ = os.path.join(self._dir, mod.relpath)
        # So a traceback shows the source line instead of a blank.
        linecache.cache[origin] = (len(source), None, source.splitlines(True), origin)
        exec(compile(source, origin, "exec"), module.__dict__)


def _info(path):
    modules, digest = read_embedded(path)
    print("SquadReplay agent -- one-file variant")
    print("  variant        : %s" % _VARIANT)
    print("  agent version  : %s" % _VERSION)
    print("  built from     : %s" % _BUILT_FROM)
    print("  modules        : %d" % len(modules))
    for name in sorted(modules):
        src = modules[name].source
        print("    %-32s %6d lines  sha256 %s" % (
            name, src.count("\n"), hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]))
    print("  embedded text  : sha256 %s" % digest)
    ok = digest == _SECTION_SHA256
    print("  matches header : %s" % ("yes" if ok else "NO -- the file was changed after it was built"))
    return 0 if ok else 1


def main():
    path = os.path.abspath(__file__)
    if sys.version_info < (3, 10):
        _die("Python 3.10 or newer is required (this is %d.%d)" % sys.version_info[:2])
    if "--bundle-info" in sys.argv[1:]:
        return _info(path)

    modules, _digest = read_embedded(path)
    if "squad_memory_reader" not in modules:
        _die("damaged bundle: the entry module is missing")

    # Before anything is imported: the rest of the agent asks agent._runtime
    # whether it is a single file (what to copy on install, what to replace
    # on update, what to relaunch, where NOT to put file capabilities).
    os.environ["SQUADREPLAY_BUNDLE"] = path

    sys.meta_path.insert(0, _Finder(modules, path))
    entry = importlib.import_module("squad_memory_reader")
    return entry._supervised_main()


if __name__ == "__main__":
    sys.exit(main())

#| ===== package: agent =====
#| """agent/__init__.py — Agent-side packaging helpers for the SquadReplay binary."""
#| from __future__ import annotations
#| __all__ = ["offset_client"]
#| ===== module: agent._enroll =====
#| """agent/_enroll.py — Agent self-enrollment bootstrap."""
#| from __future__ import annotations
#| import json
#| import logging
#| import os
#| import sys
#| import urllib.error
#| import urllib.request
#| from pathlib import Path
#| logger = logging.getLogger("squad_agent.enroll")
#| # Where the operator may stash the token. Checked in this order;
#| _TOKEN_ENV_VAR  = "SQUAD_ENROLL_TOKEN"
#| _TOKEN_FILENAME = "enroll.txt"
#| # Default URL the agent calls when nothing better is configured.
#| _DEFAULT_BASE_URL = "https://squadreplay.com"
#| # Connection timeout. The endpoint is fast (single registry write +
#| _HTTP_TIMEOUT_S = 30
#| def _binary_dir() -> Path:
#|     """Directory next to the running binary / source. Used as the"""
#|     onefile_dir = os.environ.get("NUITKA_ONEFILE_DIRECTORY")
#|     if onefile_dir:
#|         p = Path(onefile_dir)
#|         if p.is_dir():
#|             return p
#|     if getattr(sys, "__compiled__", None):
#|         try:
#|             launcher = Path(sys.executable).resolve()
#|             if launcher.is_file():
#|                 return launcher.parent
#|         except OSError:
#|             pass
#|     # Source-level dev run.
#|     return Path(__file__).resolve().parent.parent
#| def _read_token() -> tuple[str, Path | None]:
#|     """Find the operator-supplied enrollment token. Returns"""
#|     cli_token = ""
#|     # Allow ``--enroll TOKEN`` anywhere on argv. We can't run the full
#|     argv = sys.argv
#|     for i, a in enumerate(list(argv)):
#|         if a == "--enroll" and i + 1 < len(argv):
#|             cli_token = argv[i + 1].strip()
#|             del argv[i:i + 2]
#|             break
#|         if a.startswith("--enroll="):
#|             cli_token = a.split("=", 1)[1].strip()
#|             del argv[i]
#|             break
#|     if cli_token:
#|         return cli_token, None
#|     env_token = (os.environ.get(_TOKEN_ENV_VAR) or "").strip()
#|     if env_token:
#|         return env_token, None
#|     here = _binary_dir()
#|     token_path = here / _TOKEN_FILENAME
#|     if token_path.is_file():
#|         try:
#|             txt = token_path.read_text(encoding="utf-8").strip()
#|         except OSError:
#|             return "", None
#|         if txt:
#|             return txt, token_path
#|     return "", None
#| def _write_env_file(env_path: Path, *, agent_id: str,
#|                     secret_storage: str,
#|                     push_url: str) -> None:
#|     body = (
#|         "# Generated by agent self-enrollment. Do not commit.\n"
#|         f"SQUAD_AGENT_ID={agent_id}\n"
#|         f"SQUAD_AGENT_SECRET_HEX={secret_storage}\n"
#|         f"SQUAD_PUSH_URL={push_url}\n"
#|     )
#|     if sys.platform.startswith("win"):
#|         env_path.write_text(body, encoding="utf-8")
#|         return
#|     # Create pre-restricted rather than write_text()-then-chmod: the
#|     fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
#|     try:
#|         os.fchmod(fd, 0o600)  # mode= above only applies on creation;
#|         # force it here too in case the file pre-existed with looser perms
#|         with os.fdopen(fd, "w", encoding="utf-8") as f:
#|             f.write(body)
#|     except OSError:
#|         pass
#| def _post_enroll(base_url: str, *, token: str,
#|                  platform: str) -> dict | None:
#|     url = base_url.rstrip("/") + "/api/enroll"
#|     body = json.dumps({
#|         "token":    token,
#|         "platform": platform,
#|     }).encode("utf-8")
#|     req = urllib.request.Request(
#|         url, data=body,
#|         headers={
#|             "Content-Type": "application/json",
#|             "User-Agent":   "SquadReplay-enroll/1.0",
#|         },
#|         method="POST",
#|     )
#|     try:
#|         with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
#|             raw = resp.read()
#|     except urllib.error.HTTPError as exc:
#|         logger.error("enroll: central returned HTTP %s", exc.code)
#|         return None
#|     except (urllib.error.URLError, TimeoutError, OSError) as exc:
#|         logger.error("enroll: cannot reach central (%s)", exc)
#|         return None
#|     try:
#|         doc = json.loads(raw.decode("utf-8"))
#|     except (UnicodeDecodeError, json.JSONDecodeError):
#|         logger.error("enroll: central response not json")
#|         return None
#|     if not isinstance(doc, dict):
#|         logger.error("enroll: central response not an object")
#|         return None
#|     return doc
#| def bootstrap_if_needed() -> bool:
#|     """Run the enrollment dance once if the install is fresh."""
#|     here = _binary_dir()
#|     env_path = here / ".env.agent"
#|     if env_path.exists():
#|         return False
#|     # Also consider already-loaded process env: an operator using the
#|     if (os.environ.get("SQUAD_AGENT_SECRET_HEX") or "").strip():
#|         return False
#|     token, token_path = _read_token()
#|     if not token:
#|         return False
#|     base_url = (os.environ.get("SQUAD_PUSH_URL") or "").strip() or _DEFAULT_BASE_URL
#|     platform = "linux" if sys.platform.startswith("linux") else sys.platform
#|     logger.info("enroll: contacting %s with platform=%s", base_url, platform)
#|     doc = _post_enroll(base_url, token=token, platform=platform)
#|     if not doc:
#|         return False
#|     agent_id   = str(doc.get("agent_id") or "").strip()
#|     secret_hex = str(doc.get("secret_hex") or "").strip().lower()
#|     push_url   = str(doc.get("push_url") or base_url).strip() or base_url
#|     if not agent_id or len(secret_hex) != 64:
#|         logger.error("enroll: central response missing fields")
#|         return False
#|     secret_storage = secret_hex
#|     try:
#|         _write_env_file(
#|             env_path,
#|             agent_id=agent_id,
#|             secret_storage=secret_storage,
#|             push_url=push_url,
#|         )
#|     except OSError as exc:
#|         logger.error("enroll: cannot write %s (%s)", env_path, exc)
#|         return False
#|     # Push values into the live env so the rest of the boot flow can
#|     os.environ.setdefault("SQUAD_AGENT_ID", agent_id)
#|     os.environ.setdefault("SQUAD_AGENT_SECRET_HEX", secret_storage)
#|     os.environ.setdefault("SQUAD_PUSH_URL", push_url)
#|     if token_path is not None:
#|         # One-time token. Delete the file so a backup snapshot or
#|         try:
#|             token_path.unlink()
#|         except OSError:
#|             pass
#|     logger.info("enroll OK: agent_id=%s, .env.agent saved at %s",
#|                 agent_id, env_path)
#|     return True
#| __all__ = ["bootstrap_if_needed"]
#| ===== module: agent._install =====
#| """agent/_install.py — Linux self-install bootstrap."""
#| from __future__ import annotations
#| import logging
#| import os
#| import re
#| import shlex
#| import shutil
#| import subprocess
#| import sys
#| from pathlib import Path
#| logger = logging.getLogger("SquadReplay.install")
#| # ---------------------------------------------------------------------------
#| def _ansi(code: str, text: str) -> str:
#|     """Wrap text in an ANSI escape sequence, but only when stdout is a TTY."""
#|     if sys.stdout.isatty():
#|         return f"\033[{code}m{text}\033[0m"
#|     return text
#| def _green(t: str)  -> str: return _ansi("1;92", t)
#| def _red(t: str)    -> str: return _ansi("1;91", t)
#| def _yellow(t: str) -> str: return _ansi("1;93", t)
#| def _bold(t: str)   -> str: return _ansi("1",    t)
#| def _dim(t: str)    -> str: return _ansi("2",    t)
#| # Keyword → operator hint mapping. First matching entry wins.
#| _INSTALL_HINTS: list[tuple[str, str]] = [
#|     ("must run as root",
#|      "Run:  sudo ./SquadReplay --install --enroll <token>"),
#|     ("no running",
#|      "Start the Squad dedicated server first, then re-run the installer."),
#|     ("multiple SquadGameServer",
#|      "Pass --force-user <username> to specify which user to run under."),
#|     ("timed out",
#|      "Token may be expired. Generate a new one:\n"
#|      "    python3 -m ingest.provision enroll-token <agent_id>"),
#|     ("expired",
#|      "Generate a new token:\n"
#|      "    python3 -m ingest.provision enroll-token <agent_id>"),
#|     ("enrollment failed",
#|      "Check network connectivity to squadreplay.com, then retry."),
#|     ("systemctl not found",
#|      "This installer requires systemd. Contact support for manual setup."),
#|     ("setpriv",
#|      "Make sure the 'util-linux' package is installed:\n"
#|      "    sudo apt-get install util-linux"),
#| ]
#| def _print_success_banner(workdir: Path, started_on_boot: bool = False) -> None:
#|     w = 50
#|     bar = "═" * w
#|     print()
#|     print(_green(f"╔{bar}╗"))
#|     print(_green("║") + _bold(_green(f"  ✓  INSTALLATION COMPLETE".center(w))) + _green("║"))
#|     print(_green(f"╚{bar}╝"))
#|     print()
#|     print(_bold("  Please start the agent with:"))
#|     print()
#|     print(f"    {_yellow('cd')} {workdir}")
#|     print(f"    {_yellow('./start.sh')}")
#|     print()
#|     print(_dim(f"  start.sh has its own restart loop, so the agent survives"))
#|     print(_dim(f"  crashes."))
#|     if started_on_boot:
#|         print(_dim(f"  A cron @reboot entry (marked '# squadreplay-autostart' in"))
#|         print(_dim(f"  the crontab) starts it again after a reboot."))
#|     else:
#|         print(_dim(f"  It will NOT come back after a reboot by itself — add a"))
#|         print(_dim(f"  cron @reboot entry, or run it in screen/tmux."))
#|     print()
#|     print(_dim(f"  Watch logs:"))
#|     print(_dim(f"    tail -f {workdir}/logs/agent.log"))
#|     print()
#| def _print_error_banner(exc: Exception) -> None:
#|     msg = str(exc)
#|     msg_lc = msg.lower()
#|     hint = next(
#|         (h for kw, h in _INSTALL_HINTS if kw.lower() in msg_lc),
#|         "Check the error message above and retry."
#|     )
#|     w = 50
#|     bar = "═" * w
#|     print()
#|     print(_red(f"╔{bar}╗"))
#|     print(_red("║") + _bold(_red("  ✗  INSTALLATION FAILED".center(w))) + _red("║"))
#|     print(_red(f"╚{bar}╝"))
#|     print()
#|     print(_red(f"  Error:  {msg}"))
#|     print()
#|     print(_bold("  Fix:"))
#|     for line in hint.splitlines():
#|         print(f"    {line}")
#|     print()
#| class InstallError(RuntimeError):
#|     """Raised when self-install hits an unrecoverable precondition."""
#| # Standard system paths used by the installer. Constants so a future
#| _SYSCTL_PATH        = Path("/etc/sysctl.d/99-squad-replay.conf")
#| _SUDOERS_VOICE_PATH = Path("/etc/sudoers.d/squad-replay-voice")
#| _DEFAULT_DEPLOY_REL = Path("BOTS") / "SquadReplay"      # under target user's $HOME
#| # ---------------------------------------------------------------------------
#| def _ensure_root() -> None:
#|     """Install touches /etc/sysctl.d and needs setcap — must be root."""
#|     if os.geteuid() != 0:
#|         raise InstallError(
#|             "self-install must run as root (sudo). Re-run with "
#|             "`sudo ./SquadReplay --install [...]`"
#|         )
#| def _ensure_linux() -> None:
#|     if not sys.platform.startswith("linux"):
#|         raise InstallError(
#|             f"self-install supports Linux only (detected: {sys.platform})"
#|         )
#| # ---------------------------------------------------------------------------
#| # Squad server binary name on Linux (without .exe). When multiple
#| _SQUAD_COMM = "SquadGameServer"
#| def _detect_squad_user_and_path() -> tuple[str, str]:
#|     """Scan /proc for a running ``SquadGameServer`` process and return"""
#|     candidates: list[tuple[int, str, str]] = []   # (pid, user, exe_path)
#|     proc_root = Path("/proc")
#|     for entry in proc_root.iterdir():
#|         if not entry.name.isdigit():
#|             continue
#|         try:
#|             comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
#|         except OSError:
#|             continue
#|         if comm != _SQUAD_COMM:
#|             continue
#|         # exe symlink points to the running binary path (visible from
#|         try:
#|             exe_path = os.readlink(entry / "exe")
#|         except OSError:
#|             continue
#|         # /proc/<pid>/status -> Uid: real effective saved fsuid
#|         try:
#|             uid_line = next(
#|                 ln for ln in (entry / "status").read_text(
#|                     encoding="utf-8", errors="ignore"
#|                 ).splitlines()
#|                 if ln.startswith("Uid:")
#|             )
#|             real_uid = int(uid_line.split()[1])
#|         except (OSError, StopIteration, ValueError, IndexError):
#|             continue
#|         # Skip root-owned Squad processes — they shouldn't exist in a
#|         if real_uid == 0:
#|             continue
#|         import pwd
#|         try:
#|             user = pwd.getpwuid(real_uid).pw_name
#|         except KeyError:
#|             continue
#|         candidates.append((int(entry.name), user, exe_path))
#|     if not candidates:
#|         raise InstallError(
#|             f"no running '{_SQUAD_COMM}' process found. Start the Squad "
#|             "dedicated server first, then re-run the installer."
#|         )
#|     if len({c[1] for c in candidates}) > 1:
#|         users = sorted({c[1] for c in candidates})
#|         raise InstallError(
#|             f"multiple SquadGameServer processes under different users "
#|             f"({', '.join(users)}). Pass --force-user <name> to pick one."
#|         )
#|     # Deterministic pick: lowest PID among same-user candidates.
#|     candidates.sort()
#|     pid, user, exe_path = candidates[0]
#|     logger.info("[install] service detected: user=%s", user)
#|     return user, exe_path
#| # ---------------------------------------------------------------------------
#| _SYSCTL_BODY = """\
#| # SquadReplay agent runtime requirement. Generated by `SquadReplay --install`.
#| # Safe to remove after uninstall; harmless to leave in place.
#| kernel.yama.ptrace_scope = 0
#| """
#| def _write_sysctl_dropin() -> None:
#|     _SYSCTL_PATH.write_text(_SYSCTL_BODY, encoding="utf-8")
#|     _SYSCTL_PATH.chmod(0o644)
#|     # Apply immediately so the current host doesn't require a reboot.
#|     try:
#|         subprocess.run(
#|             ["sysctl", "--load", str(_SYSCTL_PATH)],
#|             check=True, capture_output=True, text=True,
#|         )
#|     except (subprocess.CalledProcessError, FileNotFoundError) as exc:
#|         # Sysctl failure is recoverable — file is on disk, next reboot
#|         logger.warning("sysctl --load failed (%s); reboot will apply on next boot", exc)
#|     logger.info("wrote %s", _SYSCTL_PATH)
#| # ---------------------------------------------------------------------------
#| def _variant_has_voice() -> bool:
#|     """Whether the variant being installed carries the voice plumbing."""
#|     try:
#|         from agent import capabilities
#|         return "voice" in capabilities.detect()
#|     except Exception:
#|         return False
#| def _apt_install_bpfcc() -> bool:
#|     """Install python3-bpfcc (the tap's bcc runtime). Best-effort: apt may be"""
#|     try:
#|         subprocess.run(["apt-get", "install", "-y", "python3-bpfcc"],
#|                        check=True, capture_output=True, text=True, timeout=600)
#|         logger.info("installed python3-bpfcc")
#|         return True
#|     except (subprocess.CalledProcessError, FileNotFoundError,
#|             subprocess.TimeoutExpired) as exc:
#|         logger.warning("could not install python3-bpfcc (%s); install it by hand "
#|                        "for voice capture", exc)
#|         return False
#| def _voice_sudoers_body(user: str, tap: Path) -> str:
#|     """The sudoers rule: ``user`` may run exactly ``/usr/bin/python3 <tap>``"""
#|     return (
#|         "# SquadReplay voice capture. Lets the agent run the eBPF voice tap as\n"
#|         "# root (it needs CAP_BPF/CAP_PERFMON) without a password. Generated by\n"
#|         "# `SquadReplay --install`. Remove this file to revoke.\n"
#|         f"{user} ALL=(root) NOPASSWD: /usr/bin/python3 {tap} *\n"
#|     )
#| def _write_voice_sudoers_dropin(user: str, workdir: Path) -> None:
#|     """Let ``user`` run the voice tap as root without a password. Pinned to the"""
#|     from agent import _runtime
#|     body = _voice_sudoers_body(user, workdir / _runtime.VOICE_TAP_FILENAME)
#|     tmp = _SUDOERS_VOICE_PATH.with_suffix(".tmp")   # a dotted name sudo ignores
#|     tmp.write_text(body, encoding="utf-8")
#|     tmp.chmod(0o440)
#|     try:
#|         subprocess.run(["visudo", "-cf", str(tmp)],
#|                        check=True, capture_output=True, text=True)
#|     except (subprocess.CalledProcessError, FileNotFoundError) as exc:
#|         tmp.unlink(missing_ok=True)
#|         logger.warning("voice sudoers rule failed validation (%s); not installed -- "
#|                        "voice capture will need manual sudo setup", exc)
#|         return
#|     os.replace(tmp, _SUDOERS_VOICE_PATH)
#|     _SUDOERS_VOICE_PATH.chmod(0o440)
#|     logger.info("wrote %s", _SUDOERS_VOICE_PATH)
#| def _maybe_setup_voice_capture(user: str, workdir: Path) -> None:
#|     if not _variant_has_voice():
#|         return
#|     logger.info("voice variant: installing python3-bpfcc + sudo rule for the tap")
#|     _apt_install_bpfcc()
#|     try:
#|         _write_voice_sudoers_dropin(user, workdir)
#|     except OSError as exc:
#|         logger.warning("voice sudoers setup failed (%s); voice needs manual sudo", exc)
#| # ---------------------------------------------------------------------------
#| # The game Port launch arg, not QueryPort: the negative lookbehind rejects a
#| _PORT_RE = re.compile(r"(?<![A-Za-z])Port=(\d+)")
#| def _detect_squad_port() -> int | None:
#|     """The game Port of a running SquadGameServer, read from its launch args."""
#|     try:
#|         from agent import _platform
#|         for _pid, cmdline in _platform.list_processes_by_name(_SQUAD_COMM):
#|             m = _PORT_RE.search(cmdline or "")
#|             if m:
#|                 return int(m.group(1))
#|     except Exception:
#|         pass
#|     return None
#| # ---------------------------------------------------------------------------
#| def _resolve_deploy_dir(user: str, override: Path | None) -> Path:
#|     if override is not None:
#|         return override.resolve()
#|     # Prefer the directory the binary is already running from — this way a
#|     onefile_dir = os.environ.get('NUITKA_ONEFILE_DIRECTORY', '')
#|     if onefile_dir:
#|         p = Path(onefile_dir).resolve()
#|         if p.is_dir():
#|             return p
#|     import pwd
#|     home = Path(pwd.getpwnam(user).pw_dir)
#|     return (home / _DEFAULT_DEPLOY_REL).resolve()
#| def _self_copy_to_deploy(deploy_dir: Path) -> Path:
#|     """Place the running binary inside ``deploy_dir`` so the systemd"""
#|     # A single-file variant (agent/_runtime.py) is a .py: the thing to put in
#|     from agent import _runtime
#|     bundle = _runtime.bundle_path()
#|     if bundle is not None:
#|         target = (deploy_dir / bundle.name).resolve()
#|         if bundle.resolve() == target:
#|             return target
#|         deploy_dir.mkdir(parents=True, exist_ok=True)
#|         shutil.copy2(bundle, target)
#|         target.chmod(0o644)
#|         logger.info("copied the agent file to %s", target)
#|         return target
#| _START_SH_BODY = """\
#| #!/usr/bin/env bash
#| # Squad Replay agent — start/restart-loop wrapper.
#| # Generated by `SquadReplay --install`. Idempotent; safe to re-run.
#| # This is the primary way to run the agent (no systemd unit is installed) —
#| # survives crashes via the loop below. After a reboot, the cron @reboot entry
#| # `--install` added to this user's crontab (marked "# squadreplay-autostart")
#| # runs this script again; `--install --no-autostart` skips that entry.
#| set -euo pipefail
#| cd "$(dirname "$0")"
#| # Enrollment computed this host's HW fingerprint as {user} (the service
#| # user, via setpriv — see _run_enroll_as_user). Root can additionally read
#| # /sys/class/dmi/id/product_uuid, which {user} cannot, so root and {user}
#| # hash to DIFFERENT fingerprints on the same machine and the binding check
#| # in squad_memory_reader.py would reject root-started runs. Re-exec as
#| # {user} so an operator who is root on the docker host (the common case)
#| # still lands on the enrolled UID.
#| if [ "$(id -un)" = "root" ]; then
#|     exec setpriv --reuid {user} --regid {user} --init-groups --no-new-privs "$(pwd)/$(basename "$0")" "$@"
#| fi
#|
#| if [ -f .env.agent ]; then
#|     set -a; . .env.agent; set +a
#| fi
#|
#| # Tells the auto-update swap helper (agent/updater.py) that WE own
#| # restarting the binary after a self-update self-replace exit — it must
#| # not also relaunch, or two readers would race PTRACE_ATTACH on the game
#| # process.
#| export SQUAD_AGENT_SUPERVISED=1
#|
#| mkdir -p logs
#|
#| # Supervisor-level messages (launch/restart/stale-kill) go straight into
#| # the same rotating log the reader itself writes (logs/agent.log) instead
#| # of a separate service.log — one file, one rotation policy (daily,
#| # 7-day FIFO — see squad_memory_reader.py's TimedRotatingFileHandler).
#| # `|| true` so a stale/unwritable log file never takes the launcher down.
#| _log() {{
#|     echo "$1"
#|     echo "$1" >> logs/agent.log 2>/dev/null || true
#| }}
#|
#| _self=$$
#| _stale=$(pgrep -f "$(pwd)/{agent_name}" 2>/dev/null | grep -v "^$_self$" || true)
#| if [ -n "$_stale" ]; then
#|     _log "=== stale process(es) detected: $_stale — sending SIGTERM ==="
#|     kill $_stale 2>/dev/null || true
#|     # Wait up to 10s for a graceful exit before escalating. A lingering
#|     # writer here would violate live_data_mmap.py's single-writer seqlock
#|     # invariant if the new instance starts while the old one still has the
#|     # mmap open — two writers tearing each other's snapshots mid-write.
#|     for _i in $(seq 1 20); do
#|         _stale=$(pgrep -f "$(pwd)/{agent_name}" 2>/dev/null | grep -v "^$_self$" || true)
#|         [ -z "$_stale" ] && break
#|         sleep 0.5
#|     done
#|     if [ -n "$_stale" ]; then
#|         _log "=== $_stale still alive after 10s, sending SIGKILL ==="
#|         kill -9 $_stale 2>/dev/null || true
#|         sleep 1
#|     fi
#| fi
#|
#| # Exit codes that won't fix themselves by restarting (see
#| # squad_memory_reader.py ~line 10500-10575): 2/5 = packaged binary missing
#| # the agent/ package (needs rebuild), 4 = central sent an unrecognised
#| # offset bundle (schema mismatch), 6 = HW fingerprint binding mismatch
#| # (needs re-enroll). Retrying these every 5s just spams the log; back off
#| # so a human has time to read the actionable message the agent already
#| # logged above.
#| _PERMANENT_RC=" 2 4 5 6 "
#|
#| # set -e must be off for the restart loop — a non-zero agent exit propagates
#| # through the pipe and kills the script, defeating the restart entirely.
#| set +e
#| while true; do
#|     _log "=== launching SquadReplay $(date) ==="
#|     {launch} "$@"
#|     _rc=$?
#|     case "$_PERMANENT_RC" in
#|         *" $_rc "*)
#|             _log "=== agent exited rc=$_rc at $(date) — config/binding issue, see message above; backing off 300s instead of hammering ==="
#|             sleep 300
#|             ;;
#|         *)
#|             _log "=== agent exited rc=$_rc at $(date); restarting in 5s ==="
#|             sleep 5
#|             ;;
#|     esac
#| done
#| """
#| def _start_sh_launch(workdir: Path) -> tuple[str, str]:
#|     """``(command to run the agent, name the stale-process sweep looks for)``."""
#|     from agent import _runtime
#|     bundle = _runtime.bundle_path()
#|     py = shlex.quote(_runtime.interpreter())
#|     return f'{py} "$(pwd)/{bundle.name}"', bundle.name
#| def _write_start_sh(workdir: Path, user: str) -> None:
#|     sh = workdir / "start.sh"
#|     if sh.exists():
#|         return
#|     launch, agent_name = _start_sh_launch(workdir)
#|     sh.write_text(
#|         _START_SH_BODY.format(user=user, launch=launch, agent_name=agent_name),
#|         encoding="utf-8",
#|     )
#|     sh.chmod(0o755)
#|     _chown_recursive(sh, user)
#|     logger.info("wrote %s", sh)
#| #: Marks the crontab line we own, so re-running --install replaces it rather
#| AUTOSTART_MARKER = "# squadreplay-autostart"
#| def _autostart_line(workdir: Path) -> str:
#|     """The cron entry that starts the agent when the host boots. ``start.sh``"""
#|     d = shlex.quote(str(workdir))
#|     return f"@reboot cd {d} && ./start.sh >> logs/boot.log 2>&1 {AUTOSTART_MARKER}\n"
#| def _merge_crontab(existing: str, line: str) -> str:
#|     """``existing`` with our entry present exactly once (any older entry of ours"""
#|     kept = [ln for ln in (existing or "").splitlines() if AUTOSTART_MARKER not in ln]
#|     return "".join(ln + "\n" for ln in kept) + line
#| def _install_autostart(user: str, workdir: Path) -> bool:
#|     """Add the @reboot entry to ``user``'s crontab. No systemd unit is installed"""
#|     line = _autostart_line(workdir)
#|     if shutil.which("crontab") is None:
#|         logger.warning("cron is not installed, so the agent will NOT come back by "
#|                        "itself after a reboot. Add this to %s's crontab by hand:\n  %s",
#|                        user, line.strip())
#|         return False
#|     try:
#|         cur = subprocess.run(["crontab", "-u", user, "-l"], capture_output=True,
#|                              text=True, timeout=20)
#|         existing = cur.stdout if cur.returncode == 0 else ""   # rc 1: no crontab yet
#|         done = subprocess.run(["crontab", "-u", user, "-"], input=_merge_crontab(existing, line),
#|                               capture_output=True, text=True, timeout=20)
#|     except (OSError, subprocess.SubprocessError) as exc:
#|         logger.warning("could not update %s's crontab (%s); add by hand:\n  %s",
#|                        user, exc, line.strip())
#|         return False
#|     if done.returncode != 0:
#|         logger.warning("could not update %s's crontab (%s); add by hand:\n  %s",
#|                        user, (done.stderr or "").strip(), line.strip())
#|         return False
#|     logger.info("agent will start by itself after a reboot (cron @reboot for %s)", user)
#|     return True
#| def _create_local_stats_db(workdir: Path, user: str) -> Path | None:
#|     """Create ``<workdir>/player-stats.sqlite`` with its schema, owned by"""
#|     from agent import local_db
#|     path = workdir / local_db.DEFAULT_FILENAME
#|     try:
#|         local_db.open_db(path).close()
#|         for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
#|             if p.exists():
#|                 _chown_recursive(p, user)
#|     except Exception as exc:  # noqa: BLE001 -- never fail the install on this
#|         logger.warning("could not create %s (%s); the agent will create it", path, exc)
#|         return None
#|     logger.info("player stats will be kept in %s", path)
#|     return path
#| def _chown_recursive(path: Path, user: str) -> None:
#|     import pwd
#|     pw = pwd.getpwnam(user)
#|     os.chown(path, pw.pw_uid, pw.pw_gid)
#|     if path.is_dir():
#|         for child in path.rglob("*"):
#|             try:
#|                 os.chown(child, pw.pw_uid, pw.pw_gid)
#|             except OSError:
#|                 pass
#| # ---------------------------------------------------------------------------
#| _USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,32}$")
#| def _run_enroll_as_user(user: str, deploy_dir: Path, binary: Path, token: str) -> None:
#|     """Drop privileges to ``user`` and invoke the binary's ``--enroll``"""
#|     if not _USERNAME_RE.match(user):
#|         raise InstallError(f"refusing to enroll under suspicious user name {user!r}")
#|     # ``--enroll-only`` makes the binary exit immediately after writing
#|     from agent import _runtime
#|     try:
#|         subprocess.run(
#|             [
#|                 "setpriv", "--reuid", user, "--regid", user, "--init-groups",
#|                 *_runtime.relaunch_argv(binary), "--enroll", token, "--enroll-only",
#|             ],
#|             cwd=str(deploy_dir),
#|             check=True,
#|             timeout=120,
#|         )
#|         logger.info("enrollment complete (.env.agent written under %s)", deploy_dir)
#|     except subprocess.TimeoutExpired:
#|         raise InstallError(
#|             "enrollment timed out after 120s — token may be expired or "
#|             "central unreachable. Generate a new token and retry."
#|         )
#|     except (subprocess.CalledProcessError, FileNotFoundError) as exc:
#|         raise InstallError(f"enrollment failed: {exc}") from exc
#| # ---------------------------------------------------------------------------
#| def install_linux(
#|     *,
#|     enroll_token: str | None = None,
#|     deploy_dir: Path | None = None,
#|     force_user: str | None = None,
#|     accept_legal: bool = False,
#|     autostart: bool = True,
#| ) -> int:
#|     """Run the full Linux self-install. Returns 0 on success or raises"""
#|     _ensure_linux()
#|     _ensure_root()
#|     # 1. Discover Squad's service user (we won't run agent as root).
#|     if force_user:
#|         if not _USERNAME_RE.match(force_user):
#|             raise InstallError(f"invalid --force-user value {force_user!r}")
#|         # Trust operator override; still require a running server (the scan
#|         _detect_squad_user_and_path()
#|         target_user = force_user
#|     else:
#|         target_user, _ = _detect_squad_user_and_path()
#|     logger.info("target service user: %s", target_user)
#|     # 2. Place binary into deploy dir under target user's home.
#|     workdir = _resolve_deploy_dir(target_user, deploy_dir)
#|     # The person installing is about to become the data controller for
#|     from agent import _legal
#|     try:
#|         _legal.require_acceptance(
#|             workdir,
#|             accept_flag=accept_legal,
#|             interactive=sys.stdin.isatty(),
#|             who=os.environ.get("SUDO_USER", "") or target_user,
#|         )
#|     except _legal.LegalNotAccepted as exc:
#|         raise InstallError(str(exc)) from exc
#|     workdir.mkdir(parents=True, exist_ok=True)
#|     (workdir / "logs").mkdir(exist_ok=True)
#|     # No replays/ dir: a pushing agent never writes replays locally -- central
#|     binary = _self_copy_to_deploy(workdir)
#|     _write_start_sh(workdir, target_user)
#|     _chown_recursive(workdir, target_user)
#|     # 3. Apply ptrace permissions (primary: sysctl drop-in; secondary: file caps).
#|     _write_sysctl_dropin()
#|     # 3b. Voice variants need python3-bpfcc + passwordless sudo for the eBPF
#|     _maybe_setup_voice_capture(target_user, workdir)
#|     # 4. Write squad_replay_config.json. The agent finds the right server by
#|     config_path = workdir / "squad_replay_config.json"
#|     if not config_path.exists():
#|         import json as _json
#|         default_port = _detect_squad_port() or 7787
#|         try:
#|             entered = input(f"[install] Squad game Port [{default_port}]: ").strip()
#|         except (EOFError, KeyboardInterrupt):
#|             entered = ""
#|         if entered.isdigit():
#|             port = int(entered)
#|         else:
#|             port = default_port
#|             if entered:
#|                 logger.warning("'%s' is not a port number; using %d", entered, port)
#|         logger.info("agent will attach to the SquadGameServer on game Port=%d", port)
#|         config_path.write_text(
#|             _json.dumps(
#|                 {
#|                     "port":                 port,
#|                     "process_name":         _SQUAD_COMM,
#|                     "attach_retry_seconds": 5,
#|                 },
#|                 indent=2,
#|             ),
#|             encoding="utf-8",
#|         )
#|         _chown_recursive(config_path, target_user)
#|         logger.info("wrote %s", config_path)
#|     # 4b. player-stats.sqlite: the community's own copy of every match's
#|     _create_local_stats_db(workdir, target_user)
#|     # 5. Enrollment — only if operator passed a token. Without it we
#|     if enroll_token:
#|         _run_enroll_as_user(target_user, workdir, binary, enroll_token)
#|     else:
#|         logger.info(
#|             "no --enroll token provided; .env.agent NOT created. "
#|             "Run `sudo -u %s %s --enroll <token>` later, then start "
#|             "the agent with `%s/start.sh`",
#|             target_user, binary, workdir,
#|         )
#|     started_on_boot = _install_autostart(target_user, workdir) if autostart else False
#|     _print_success_banner(workdir, started_on_boot)
#|     return 0
#| __all__ = ["install_linux", "InstallError", "_print_error_banner"]
#| ===== module: agent._legal =====
#| """agent/_legal.py — show the legal notice and record that it was accepted."""
#| from __future__ import annotations
#| import json
#| import time
#| from pathlib import Path
#| from typing import Callable
#| #: Bump when the notice changes materially; it re-prompts existing installs.
#| NOTICE_VERSION = 1
#| #: What the person has to type. Not "y": a reflex keystroke is not consent.
#| PHRASE = "I ACCEPT"
#| LEGAL_URL = "https://github.com/BlueMoonTR/SquadReplay/blob/main/LEGAL.md"
#| ACCEPTANCE_FILE = "legal_accepted.json"
#| NOTICE = f"""\
#| SquadReplay agent -- legal notice (version {NOTICE_VERSION})
#|
#| This agent records match data from YOUR Squad server: players' in-game
#| names and IDs, positions, kills and damage, and chat. The voice variants
#| also record players' in-game voice.
#|
#|   * YOU, the server owner, are the data controller for that data under the
#|     GDPR and Turkey's KVKK. SquadReplay is the tool provider that
#|     processes it on your behalf.
#|   * You must tell your players BEFORE data is collected: what is recorded,
#|     why, where it is stored, for how long, and how to reach you.
#|   * Recording VOICE requires players' explicit consent. A player who has
#|     not consented must not be recorded.
#|   * You handle your players' access, correction and deletion requests, and
#|     meet any registration or cross-border transfer rules that apply to you.
#|   * SquadReplay is not liable for claims or fines arising from your not
#|     doing these things, and the software is provided "as is".
#|
#| Full text and a player privacy-notice template:
#|   {LEGAL_URL}
#| """
#| class LegalNotAccepted(RuntimeError):
#|     """The notice was not accepted; the install must not continue."""
#| def accepted_version(workdir: Path) -> int | None:
#|     """The notice version recorded in ``workdir``, or None."""
#|     try:
#|         doc = json.loads((Path(workdir) / ACCEPTANCE_FILE).read_text(encoding="utf-8"))
#|         v = doc.get("notice_version")
#|         return v if isinstance(v, int) and not isinstance(v, bool) else None
#|     except (OSError, ValueError, AttributeError):
#|         return None
#| def already_accepted(workdir: Path) -> bool:
#|     """True when this install has accepted the CURRENT notice."""
#|     v = accepted_version(workdir)
#|     return v is not None and v >= NOTICE_VERSION
#| def _record(workdir: Path, how: str, who: str) -> None:
#|     workdir = Path(workdir)
#|     workdir.mkdir(parents=True, exist_ok=True)
#|     (workdir / ACCEPTANCE_FILE).write_text(
#|         json.dumps({
#|             "notice_version": NOTICE_VERSION,
#|             "accepted_at": int(time.time()),
#|             "how": how,
#|             "user": who,
#|         }, indent=2) + "\n",
#|         encoding="utf-8",
#|     )
#| def require_acceptance(
#|     workdir: Path,
#|     *,
#|     accept_flag: bool,
#|     interactive: bool,
#|     who: str = "",
#|     input_fn: Callable[[str], str] = input,
#|     out: Callable[[str], None] = print,
#| ) -> bool:
#|     """Make sure the current notice has been accepted for this install."""
#|     if already_accepted(workdir):
#|         return False
#|     out(NOTICE)
#|     if accept_flag:
#|         _record(workdir, "flag", who)
#|         out("Legal notice accepted with --accept-legal.")
#|         return True
#|     if not interactive:
#|         raise LegalNotAccepted(
#|             "The legal notice above has not been accepted, and there is no "
#|             "terminal to ask on. Read it, then re-run with --accept-legal "
#|             "if you accept it."
#|         )
#|     try:
#|         answer = input_fn(f'Type "{PHRASE}" to accept and continue: ')
#|     except (EOFError, KeyboardInterrupt) as exc:
#|         raise LegalNotAccepted("The legal notice was not accepted.") from exc
#|     if answer.strip() != PHRASE:
#|         raise LegalNotAccepted(
#|             f'Not accepted (you must type exactly "{PHRASE}"). Nothing was installed.'
#|         )
#|     _record(workdir, "typed", who)
#|     out("Legal notice accepted.")
#|     return True
#| __all__ = [
#|     "ACCEPTANCE_FILE", "LEGAL_URL", "NOTICE", "NOTICE_VERSION", "PHRASE",
#|     "LegalNotAccepted", "accepted_version", "already_accepted",
#|     "require_acceptance",
#| ]
#| ===== module: agent._platform =====
#| """agent/_platform.py — Linux process shims for the agent."""
#| from __future__ import annotations
#| import logging
#| import os
#| import sys
#| from pathlib import Path
#| logger = logging.getLogger("squad_agent.platform")
#| IS_LINUX = sys.platform.startswith("linux")
#| # ---------------------------------------------------------------------------
#| def find_pid(image_name: str, executable_path: str | None = None,
#|              match_cmdline: str | None = None) -> int | None:
#|     """Return the PID of a running process matching ``image_name``."""
#|     if IS_LINUX:
#|         return _find_pid_linux(image_name, executable_path, match_cmdline)
#|     raise NotImplementedError(f"find_pid: unsupported platform {sys.platform}")
#| def _find_pid_linux(image_name: str, executable_path: str | None,
#|                     match_cmdline: str | None = None) -> int | None:
#|     """Walk ``/proc`` and match on ``comm`` + ``exe`` symlink + cmdline."""
#|     target_comm = image_name
#|     if target_comm.endswith(".exe"):
#|         target_comm = target_comm[:-4]
#|     target_comm = target_comm[:15]  # kernel truncates comm to 16 bytes incl. NUL
#|     target_path = str(Path(executable_path).resolve()) if executable_path else None
#|     cmd_needle = (match_cmdline or "").strip() or None
#|     proc_root = Path("/proc")
#|     try:
#|         pid_dirs = [p for p in proc_root.iterdir() if p.name.isdigit()]
#|     except OSError as e:
#|         logger.warning("cannot read /proc: %s", e)
#|         return None
#|     # Two-phase candidate collection:
#|     exact_candidates: list[int] = []
#|     inode_candidates: list[int] = []
#|     # Resolve target inode once (avoid repeated stat inside the loop)
#|     tgt_ino: tuple[int, int] | None = None
#|     if target_path is not None:
#|         try:
#|             s = os.stat(target_path)
#|             tgt_ino = (s.st_ino, s.st_dev)
#|         except OSError:
#|             pass  # target doesn't exist; inode match impossible
#|     for pid_dir in pid_dirs:
#|         try:
#|             comm = (pid_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
#|         except OSError:
#|             continue
#|         if comm != target_comm:
#|             continue
#|         if target_path is not None:
#|             try:
#|                 exe_real = os.readlink(pid_dir / "exe")
#|             except OSError:
#|                 continue
#|             if exe_real == target_path:
#|                 exact_candidates.append(int(pid_dir.name))
#|             elif tgt_ino is not None:
#|                 # Exact text path mismatch — try inode comparison for
#|                 try:
#|                     exe_st = os.stat(pid_dir / "exe")
#|                     if (exe_st.st_ino, exe_st.st_dev) == tgt_ino:
#|                         inode_candidates.append(int(pid_dir.name))
#|                 except OSError:
#|                     pass
#|         else:
#|             # No target_path configured — accept any process with matching comm.
#|             exact_candidates.append(int(pid_dir.name))
#|     # Prefer exact matches; fall back to inode matches.
#|     candidates = exact_candidates if exact_candidates else inode_candidates
#|     # Apply optional cmdline filter.
#|     if cmd_needle is not None:
#|         filtered: list[int] = []
#|         for pid in candidates:
#|             try:
#|                 raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
#|             except OSError:
#|                 continue
#|             cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
#|             if cmd_needle in cmdline:
#|                 filtered.append(pid)
#|         candidates = filtered
#|     if not candidates:
#|         return None
#|     if len(candidates) > 1 and not inode_candidates:
#|         # Multiple exact matches — unusual but return first silently.
#|         return candidates[0]
#|     if len(candidates) > 1 and inode_candidates:
#|         # Multiple containers sharing the same binary inode and no
#|         pids_str = ", ".join(str(p) for p in candidates)
#|         logger.warning(
#|             "Multiple service instances share the same binary "
#|             "(%s — PIDs %s). Add \"match_cmdline\" to "
#|             "squad_replay_config.json (e.g. \"Port=7787\") to "
#|             "select the right instance.",
#|             target_path,
#|             pids_str,
#|         )
#|         return None
#|     return candidates[0]
#| # ---------------------------------------------------------------------------
#| def is_pid_alive(pid: int | None) -> bool:
#|     """True when ``pid`` maps to a running process on this host."""
#|     if not pid or pid <= 0:
#|         return False
#|     if IS_LINUX:
#|         return _is_pid_alive_linux(pid)
#|     raise NotImplementedError(f"is_pid_alive: unsupported platform {sys.platform}")
#| def _is_pid_alive_linux(pid: int) -> bool:
#|     """``os.kill(pid, 0)`` — signal 0 is a no-op probe; raises"""
#|     try:
#|         os.kill(int(pid), 0)
#|         return True
#|     except ProcessLookupError:
#|         return False
#|     except PermissionError:
#|         return True
#|     except OSError:
#|         return False
#| # ---------------------------------------------------------------------------
#| def list_processes_by_name(image_name: str) -> list[tuple[int, str]]:
#|     """Return (pid, command_line) pairs for every running process whose"""
#|     if IS_LINUX:
#|         return _list_processes_linux(image_name)
#|     raise NotImplementedError(
#|         f"list_processes_by_name: unsupported platform {sys.platform}"
#|     )
#| def _list_processes_linux(image_name: str) -> list[tuple[int, str]]:
#|     target_comm = image_name[:-4] if image_name.endswith(".exe") else image_name
#|     target_comm = target_comm[:15]
#|     proc_root = Path("/proc")
#|     results: list[tuple[int, str]] = []
#|     try:
#|         entries = [p for p in proc_root.iterdir() if p.name.isdigit()]
#|     except OSError:
#|         return results
#|     for pid_dir in entries:
#|         try:
#|             comm = (pid_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
#|         except OSError:
#|             continue
#|         if comm != target_comm:
#|             continue
#|         try:
#|             cmdline = (pid_dir / "cmdline").read_bytes().decode("utf-8", errors="replace")
#|             # /proc exposes cmdline as NUL-separated argv. Humanify.
#|             cmdline = cmdline.replace("\x00", " ").strip()
#|         except OSError:
#|             cmdline = ""
#|         try:
#|             pid = int(pid_dir.name)
#|         except ValueError:
#|             continue
#|         results.append((pid, cmdline))
#|     return results
#| __all__ = [
#|     "IS_LINUX",
#|     "find_pid",
#|     "is_pid_alive",
#|     "list_processes_by_name",
#| ]
#| ===== module: agent._runtime =====
#| """agent/_runtime.py -- is this process a downloaded single-file variant?"""
#| from __future__ import annotations
#| import os
#| import sys
#| from pathlib import Path
#| BUNDLE_ENV = "SQUADREPLAY_BUNDLE"
#| # Where a voice variant materialises the eBPF tap so the root system-python
#| VOICE_TAP_FILENAME = "squadreplay-voice-tap.py"
#| def voice_tap_path() -> Path | None:
#|     """The on-disk path the voice tap is extracted to, or None when this is"""
#|     b = bundle_path()
#|     return (b.parent / VOICE_TAP_FILENAME) if b else None
#| def bundle_path() -> Path | None:
#|     """The running single-file agent, or None when this is not one."""
#|     raw = os.environ.get(BUNDLE_ENV)
#|     if not raw:
#|         return None
#|     p = Path(raw)
#|     return p if p.is_file() else None
#| def is_bundle() -> bool:
#|     return bundle_path() is not None
#| def interpreter() -> str:
#|     """The Python that runs the bundle -- what a relaunch must start."""
#|     return sys.executable or "python3"
#| def relaunch_argv(path: Path) -> list[str]:
#|     """The command that starts ``path`` again: the interpreter and the file"""
#|     if is_bundle():
#|         return [interpreter(), str(path)]
#|     return [str(path)]
#| __all__ = ["BUNDLE_ENV", "VOICE_TAP_FILENAME", "bundle_path", "interpreter",
#|            "is_bundle", "relaunch_argv", "voice_tap_path"]
#| ===== module: agent.capabilities =====
#| """agent/capabilities.py — what this agent build can actually do."""
#| from __future__ import annotations
#| import functools
#| import importlib
#| READ = "read"
#| WRITE = "write"
#| VOICE = "voice"
#| # What makes a build a write build is the write PRIMITIVE being in the file.
#| _WRITE_MODULES = ("agent.memory_write",)
#| # A voice build carries the capture plumbing in the file (the tap's address
#| _VOICE_MODULES = ("agent.voice_run", "agent.voice_enricher", "agent.voice_tap")
#| def _importable(name: str) -> bool:
#|     try:
#|         importlib.import_module(name)
#|     except ImportError:
#|         return False
#|     return True
#| @functools.lru_cache(maxsize=1)
#| def detect() -> tuple[str, ...]:
#|     """The capabilities this build carries, in a stable order. Cached:"""
#|     caps = [READ]
#|     if all(_importable(m) for m in _WRITE_MODULES):
#|         caps.append(WRITE)
#|     if all(_importable(m) for m in _VOICE_MODULES):
#|         caps.append(VOICE)
#|     return tuple(caps)
#| def header_value(caps: tuple[str, ...] | None = None) -> str:
#|     """``read,write`` -- the X-Agent-Capabilities header."""
#|     return ",".join(caps if caps is not None else detect())
#| def variant_name(caps: tuple[str, ...] | None = None) -> str:
#|     """``read`` / ``read-write`` -- the name the release files use."""
#|     return "-".join(caps if caps is not None else detect())
#| ===== module: agent.control_client =====
#| """agent/control_client.py — Agent-side remote-control poll/upload client."""
#| from __future__ import annotations
#| import base64
#| import json
#| import logging
#| import re
#| import secrets
#| import time
#| import urllib.error
#| import urllib.request
#| from typing import Any
#| from ingest import protocol as ingest_protocol
#| from ingest.crypto import CryptoError, EncryptedEnvelope
#| from ingest.offsets import open_response_envelope
#| logger = logging.getLogger("SquadReplay")
#| # Matches any run of 32+ lowercase-hex characters — long enough to catch
#| _HEX_SECRET_RE = re.compile(r"(?i)\b[0-9a-f]{32,}\b")
#| _REDACTED = "<redacted>"
#| def redact_log_text(text: str) -> str:
#|     """Best-effort scrub of long hex-looking runs from a log excerpt."""
#|     if not isinstance(text, str):
#|         return ""
#|     return _HEX_SECRET_RE.sub(_REDACTED, text)
#| class ControlFetchError(Exception):
#|     """Raised when the control poll cannot be completed / verified."""
#| def _b64url_decode(s: str) -> bytes:
#|     if not isinstance(s, str):
#|         raise ValueError("base64url field must be a string")
#|     pad = "=" * (-len(s) % 4)
#|     return base64.urlsafe_b64decode(s + pad)
#| def fetch_control(
#|     *,
#|     base_url: str,
#|     agent_id: str,
#|     agent_secret: bytes,
#|     timeout: float = 10.0,
#| ) -> str | None:
#|     """Poll central for a pending manager-queued command."""
#|     url = base_url.rstrip("/") + "/agent/control"
#|     seq = secrets.randbits(31)
#|     ts = int(time.time())
#|     req_body = ingest_protocol.encode_envelope(
#|         agent_id=agent_id,
#|         seq=seq,
#|         agent_secret=agent_secret,
#|         snapshot_json=json.dumps({"want": "control"}).encode("utf-8"),
#|         ts=ts,
#|     )
#|     req = urllib.request.Request(
#|         url,
#|         data=req_body,
#|         headers={
#|             "Content-Type": "application/json",
#|             "User-Agent":   "SquadReplay/1.0",
#|         },
#|         method="POST",
#|     )
#|     try:
#|         with urllib.request.urlopen(req, timeout=timeout) as resp:
#|             raw = resp.read()
#|     except urllib.error.HTTPError as e:
#|         raise ControlFetchError(f"HTTP {e.code} from central") from e
#|     except (urllib.error.URLError, TimeoutError, OSError) as e:
#|         raise ControlFetchError(f"transport error: {e}") from e
#|     try:
#|         doc = json.loads(raw)
#|         nonce = _b64url_decode(doc["nonce"])
#|         ciphertext = _b64url_decode(doc["ciphertext"])
#|     except (json.JSONDecodeError, KeyError, ValueError) as e:
#|         raise ControlFetchError(f"bad response shape: {e}") from e
#|     env = EncryptedEnvelope(nonce=nonce, ciphertext=ciphertext)
#|     try:
#|         plaintext = open_response_envelope(
#|             agent_secret,
#|             env,
#|             agent_id=agent_id,
#|             seq=seq,
#|             ts=ts,
#|         )
#|     except CryptoError as e:
#|         raise ControlFetchError(f"response decrypt failed: {e}") from e
#|     try:
#|         body: dict[str, Any] = json.loads(plaintext)
#|     except (json.JSONDecodeError, ValueError) as e:
#|         raise ControlFetchError(f"response not json: {e}") from e
#|     if not isinstance(body, dict):
#|         raise ControlFetchError("response must be a json object")
#|     command = body.get("command")
#|     if command is None:
#|         return None
#|     if command not in ("restart", "fetch_logs", "diagnose"):
#|         # Forward-compat: a future central build might send a command
#|         logger.debug("control: unrecognised command %r — ignoring", command)
#|         return None
#|     return command
#| def upload_log_result(
#|     *,
#|     base_url: str,
#|     agent_id: str,
#|     agent_secret: bytes,
#|     log_tail: str,
#|     truncated: bool,
#|     timeout: float = 10.0,
#| ) -> None:
#|     """Best-effort upload of a redacted log tail after a ``fetch_logs``"""
#|     url = base_url.rstrip("/") + "/agent/control/log_result"
#|     seq = secrets.randbits(31)
#|     ts = int(time.time())
#|     try:
#|         req_body = ingest_protocol.encode_envelope(
#|             agent_id=agent_id,
#|             seq=seq,
#|             agent_secret=agent_secret,
#|             snapshot_json=json.dumps({
#|                 "log_tail": log_tail,
#|                 "truncated": bool(truncated),
#|             }).encode("utf-8"),
#|             ts=ts,
#|         )
#|     except (TypeError, ValueError) as e:
#|         logger.warning("control: failed to encode log_result envelope: %s", e)
#|         return
#|     req = urllib.request.Request(
#|         url,
#|         data=req_body,
#|         headers={
#|             "Content-Type": "application/json",
#|             "User-Agent":   "SquadReplay/1.0",
#|         },
#|         method="POST",
#|     )
#|     try:
#|         with urllib.request.urlopen(req, timeout=timeout) as resp:
#|             resp.read()
#|     except urllib.error.HTTPError as e:
#|         logger.warning("control: log_result upload rejected: HTTP %s", e.code)
#|     except (urllib.error.URLError, TimeoutError, OSError) as e:
#|         logger.warning("control: log_result upload failed (transport): %s", e)
#| CONTROL_POLL_SECONDS = 30.0
#| LOG_TAIL_LINES = 200
#| LOG_TAIL_BYTES = 51_200
#| def tail_log(path):
#|     """The last 200 lines (at most 50 KiB) of the agent's own log as ``(text, truncated)``,"""
#|     from pathlib import Path
#|     try:
#|         raw = Path(path).read_text(encoding="utf-8", errors="replace")
#|     except OSError as exc:
#|         logger.warning("control: cannot read %s: %s", path, exc)
#|         return None
#|     lines = raw.splitlines()
#|     truncated = len(lines) > LOG_TAIL_LINES
#|     text = "\n".join(lines[-LOG_TAIL_LINES:])
#|     if len(text.encode("utf-8")) > LOG_TAIL_BYTES:
#|         truncated, text = True, text[-LOG_TAIL_BYTES:]
#|     return text, truncated
#| def run_background(*, base_url, agent_id, agent_secret, log_path, restart):
#|     """Ask central every 30 s whether the manager queued something. ``restart`` runs once and ends"""
#|     while True:
#|         try:
#|             command = fetch_control(base_url=base_url, agent_id=agent_id, agent_secret=agent_secret)
#|         except ControlFetchError as exc:
#|             logger.debug("control: poll failed (%s), retrying", exc)
#|             command = None
#|         if command == "restart":
#|             restart()
#|             return
#|         if command == "fetch_logs":
#|             tail = tail_log(log_path)
#|             if tail is not None:
#|                 upload_log_result(base_url=base_url, agent_id=agent_id, agent_secret=agent_secret,
#|                                   log_tail=redact_log_text(tail[0]), truncated=tail[1])
#|         time.sleep(CONTROL_POLL_SECONDS)
#| ===== module: agent.local_db =====
#| """agent/local_db.py -- the community's own copy of its match stats."""
#| from __future__ import annotations
#| import json
#| import os
#| import sqlite3
#| from pathlib import Path
#| from typing import Any
#| DEFAULT_FILENAME = "player-stats.sqlite"
#| SCHEMA_VERSION = 4   # 2: voice_*_s, 3: sl_squad_objective, 4: sl_squad_breakdown
#| # Column order of each table after its match_id -- the same order as
#| MATCH_PLAYER = (
#|     ("eos_id", "TEXT NOT NULL"),
#|     ("team_id", "INTEGER"),
#|     ("squad_id", "INTEGER"),
#|     ("squad_name", "TEXT"),
#|     ("squad_locked", "INTEGER"),
#|     ("role_id", "TEXT"),
#|     ("is_squad_leader", "INTEGER"),
#|     ("is_commander", "INTEGER"),
#|     ("kills", "INTEGER"),
#|     ("deaths", "INTEGER"),
#|     ("wounds", "INTEGER"),
#|     ("woundeds", "INTEGER"),
#|     ("teamkills", "INTEGER"),
#|     ("vehicle_kills", "INTEGER"),
#|     ("revived_pts", "REAL"),
#|     ("heal_pts", "REAL"),
#|     ("score", "REAL"),
#|     ("teamwork_score", "REAL"),
#|     ("objective_score", "REAL"),
#|     ("combat_score", "REAL"),
#|     ("time_played_s", "INTEGER"),
#|     ("time_as_sl_s", "INTEGER"),
#|     ("time_as_ftl_s", "INTEGER"),
#|     ("time_as_commander_s", "INTEGER"),
#|     ("infantry_distance_m", "REAL"),
#|     ("vehicle_distance_m", "REAL"),
#|     ("longest_kill_m", "REAL"),
#|     ("longest_kill_weapon", "TEXT"),
#|     ("longest_kill_vehicle", "TEXT"),
#|     ("longest_kill_seat", "INTEGER"),
#|     ("kills_inf", "INTEGER"),
#|     ("kills_veh", "INTEGER"),
#|     ("deaths_inf", "INTEGER"),
#|     ("deaths_veh", "INTEGER"),
#|     ("vehicle_kills_inf", "INTEGER"),
#|     ("vehicle_kills_veh", "INTEGER"),
#|     ("wounds_inf", "INTEGER"),
#|     ("wounds_veh", "INTEGER"),
#|     ("was_winner", "INTEGER"),
#|     ("squads_led", "INTEGER"),
#|     ("supplies_delivered", "INTEGER"),
#|     ("fobs_destroyed", "INTEGER"),
#|     ("fobs_built", "INTEGER"),
#|     ("habs_built", "INTEGER"),
#|     ("rallies_placed", "INTEGER"),
#|     ("vehicle_damage", "INTEGER"),
#|     ("captures", "INTEGER"),
#|     ("defenses", "INTEGER"),
#|     ("time_admin_cam_s", "INTEGER"),
#|     ("time_in_squad_s", "INTEGER"),
#|     # seconds transmitting per voice net (NULL: the reader didn't report it)
#|     ("voice_local_s", "INTEGER"),
#|     ("voice_squad_s", "INTEGER"),
#|     ("voice_command_s", "INTEGER"),
#|     ("voice_to_commander_s", "INTEGER"),
#|     ("voice_commander_to_squad_s", "INTEGER"),
#|     # Manga Bayrak Puanı: squad objective points while he was its SL
#|     ("sl_squad_objective", "REAL"),
#|     # {squad name: seconds as its SL}, JSON text
#|     ("sl_squad_breakdown", "TEXT"),
#| )
#| KILL_EVENT = (
#|     ("t_seconds", "INTEGER"),
#|     ("killer_eos", "TEXT"),
#|     ("victim_eos", "TEXT"),
#|     ("killer_team", "INTEGER"),
#|     ("victim_team", "INTEGER"),
#|     ("weapon_class", "TEXT"),
#|     ("distance_m", "REAL"),
#|     ("killer_in_vehicle", "INTEGER"),
#|     ("killer_vehicle_class", "TEXT"),
#|     ("killer_seat", "INTEGER"),
#|     ("victim_in_vehicle", "INTEGER"),
#|     ("victim_vehicle_class", "TEXT"),
#|     ("was_teamkill", "INTEGER"),
#|     ("damage_type", "TEXT"),
#|     ("is_vehicle_weapon", "INTEGER"),
#|     ("killer_x", "REAL"),
#|     ("killer_y", "REAL"),
#|     ("victim_x", "REAL"),
#|     ("victim_y", "REAL"),
#| )
#| VEHICLE_SESSION = (
#|     ("eos_id", "TEXT"),
#|     ("vehicle_class", "TEXT"),
#|     ("seat", "INTEGER"),
#|     ("entered_at_s", "INTEGER"),
#|     ("exited_at_s", "INTEGER"),
#|     ("distance_m", "REAL"),
#|     ("kills_in_seat", "INTEGER"),
#| )
#| def _cols(spec) -> str:
#|     return ",\n    ".join(f"{name} {typ}" for name, typ in spec)
#| SCHEMA = f"""
#| CREATE TABLE IF NOT EXISTS meta (
#|     key   TEXT PRIMARY KEY,
#|     value TEXT
#| );
#|
#| -- One row per match. complete = 1 once the match's end (or a map
#| -- change to the training range) was seen; 0 while it is running, or if
#| -- the agent missed its end.
#| CREATE TABLE IF NOT EXISTS match (
#|     match_id    TEXT PRIMARY KEY,
#|     server_id   TEXT,
#|     layer       TEXT,
#|     game_mode   TEXT,
#|     started_at  TEXT,
#|     ended_at    TEXT,
#|     duration_s  INTEGER,
#|     t1_faction  TEXT,
#|     t2_faction  TEXT,
#|     t1_tickets  INTEGER,
#|     t2_tickets  INTEGER,
#|     winner      INTEGER,
#|     snap_count  INTEGER,
#|     complete    INTEGER NOT NULL DEFAULT 0,
#|     updated_at  TEXT
#| );
#|
#| CREATE TABLE IF NOT EXISTS player (
#|     eos_id     TEXT PRIMARY KEY,
#|     steam_id   TEXT,
#|     last_name  TEXT,
#|     clan_tag   TEXT,
#|     first_seen TEXT,
#|     last_seen  TEXT
#| );
#|
#| CREATE TABLE IF NOT EXISTS match_player (
#|     match_id TEXT NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
#|     {_cols(MATCH_PLAYER)},
#|     PRIMARY KEY (match_id, eos_id)
#| );
#| CREATE INDEX IF NOT EXISTS match_player_eos ON match_player(eos_id);
#|
#| CREATE TABLE IF NOT EXISTS kill_event (
#|     match_id TEXT NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
#|     {_cols(KILL_EVENT)}
#| );
#| CREATE INDEX IF NOT EXISTS kill_event_match ON kill_event(match_id);
#| CREATE INDEX IF NOT EXISTS kill_event_killer ON kill_event(killer_eos);
#| CREATE INDEX IF NOT EXISTS kill_event_victim ON kill_event(victim_eos);
#|
#| CREATE TABLE IF NOT EXISTS vehicle_session (
#|     match_id TEXT NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
#|     {_cols(VEHICLE_SESSION)}
#| );
#| CREATE INDEX IF NOT EXISTS vehicle_session_match ON vehicle_session(match_id);
#|
#| -- The running match's accumulator, saved with every flush so an agent
#| -- restart resumes it instead of starting the match over. One row.
#| CREATE TABLE IF NOT EXISTS mirror_state (
#|     id         INTEGER PRIMARY KEY CHECK (id = 1),
#|     saved_at   TEXT,
#|     state_json TEXT NOT NULL
#| );
#| """
#| def open_db(path: str | os.PathLike) -> sqlite3.Connection:
#|     """Open (creating if absent) the stats file with its schema applied."""
#|     path = Path(path)
#|     if not path.exists():
#|         # Create it 0600 before SQLite touches it: SQLite then gives the
#|         fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
#|         os.close(fd)
#|     conn = sqlite3.connect(str(path), timeout=5.0)
#|     conn.execute("PRAGMA journal_mode=WAL")
#|     conn.execute("PRAGMA foreign_keys=ON")
#|     conn.execute("PRAGMA busy_timeout=5000")
#|     with conn:
#|         conn.executescript(SCHEMA)
#|         _add_missing_columns(conn, "match_player", MATCH_PLAYER)
#|         _add_missing_columns(conn, "kill_event", KILL_EVENT)
#|         _add_missing_columns(conn, "vehicle_session", VEHICLE_SESSION)
#|         conn.execute(
#|             "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
#|             "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
#|             (str(SCHEMA_VERSION),))
#|     return conn
#| def _add_missing_columns(conn: sqlite3.Connection, table: str, spec) -> None:
#|     """Bring a file made by an older agent up to this schema: CREATE TABLE"""
#|     have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
#|     for name, typ in spec:
#|         if name not in have:
#|             conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} "
#|                          f"{typ.replace(' NOT NULL', '')}")
#| def _sql_value(v):
#|     """Dicts (sl_squad_breakdown) are stored as JSON text."""
#|     return json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v
#| def _insert_sql(table: str, spec) -> str:
#|     names = ["match_id"] + [n for n, _ in spec]
#|     return (f"INSERT INTO {table} ({', '.join(names)}) "
#|             f"VALUES ({', '.join('?' * len(names))})")
#| _MP_SQL = _insert_sql("match_player", MATCH_PLAYER)
#| _KE_SQL = _insert_sql("kill_event", KILL_EVENT)
#| _VS_SQL = _insert_sql("vehicle_session", VEHICLE_SESSION)
#| def _delete_match_rows(conn: sqlite3.Connection, match_id: str) -> None:
#|     for table in ("match_player", "kill_event", "vehicle_session"):
#|         conn.execute(f"DELETE FROM {table} WHERE match_id = ?", (match_id,))
#| def write_match(conn: sqlite3.Connection, *, match_id: str,
#|                 server_id: str | None, started_at: str, ended_at: str | None,
#|                 result: dict[str, Any], complete: bool, now: str,
#|                 state: dict[str, Any] | None) -> None:
#|     """Write one ``MatchAccumulator.finalize()`` result, replacing the"""
#|     with conn:
#|         _delete_match_rows(conn, match_id)
#|         if result.get("skipped"):
#|             conn.execute("DELETE FROM match WHERE match_id = ?", (match_id,))
#|         else:
#|             m = result["match"]
#|             conn.execute(
#|                 """
#|                 INSERT INTO match (match_id, server_id, layer, game_mode,
#|                                    started_at, ended_at, duration_s,
#|                                    t1_faction, t2_faction, t1_tickets, t2_tickets,
#|                                    winner, snap_count, complete, updated_at)
#|                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
#|                 ON CONFLICT(match_id) DO UPDATE SET
#|                     server_id = excluded.server_id,
#|                     layer = excluded.layer,
#|                     game_mode = excluded.game_mode,
#|                     ended_at = excluded.ended_at,
#|                     duration_s = excluded.duration_s,
#|                     t1_faction = excluded.t1_faction,
#|                     t2_faction = excluded.t2_faction,
#|                     t1_tickets = excluded.t1_tickets,
#|                     t2_tickets = excluded.t2_tickets,
#|                     winner = excluded.winner,
#|                     snap_count = excluded.snap_count,
#|                     complete = excluded.complete,
#|                     updated_at = excluded.updated_at
#|                 """,
#|                 (match_id, server_id, m["layer"], m["game_mode"],
#|                  started_at, ended_at, m["duration_s"],
#|                  m["t1_faction"], m["t2_faction"], m["t1_tickets"], m["t2_tickets"],
#|                  m["winner"], result["snap_count"], int(bool(complete)), now))
#|             for p in result["players"]:
#|                 steam = p.get("steam_id")
#|                 conn.execute(
#|                     """
#|                     INSERT INTO player (eos_id, steam_id, last_name, clan_tag,
#|                                         first_seen, last_seen)
#|                     VALUES (?, ?, ?, ?, ?, ?)
#|                     ON CONFLICT(eos_id) DO UPDATE SET
#|                         steam_id   = COALESCE(excluded.steam_id, player.steam_id),
#|                         -- No plausible name all match: keep the one on file.
#|                         last_name  = CASE WHEN excluded.last_name = ''
#|                                           THEN player.last_name
#|                                           ELSE excluded.last_name END,
#|                         -- The match's own tag, '' included (central's rule:
#|                         -- the accumulator already kept any tag seen).
#|                         clan_tag   = excluded.clan_tag,
#|                         first_seen = MIN(player.first_seen, excluded.first_seen),
#|                         last_seen  = MAX(player.last_seen, excluded.last_seen)
#|                     """,
#|                     (p["eos_id"], None if steam is None else str(steam),
#|                      p["last_name"], p["clan_tag"], started_at, started_at))
#|             conn.executemany(_MP_SQL, [
#|                 (match_id,) + tuple(_sql_value(r.get(n)) for n, _ in MATCH_PLAYER)
#|                 for r in result["match_players"]])
#|             conn.executemany(_KE_SQL, [
#|                 (match_id,) + tuple(r.get(n) for n, _ in KILL_EVENT)
#|                 for r in result["kill_events"]])
#|             conn.executemany(_VS_SQL, [
#|                 (match_id,) + tuple(r.get(n) for n, _ in VEHICLE_SESSION)
#|                 for r in result["vehicle_sessions"]])
#|         if state is None:
#|             conn.execute("DELETE FROM mirror_state")
#|         else:
#|             conn.execute(
#|                 "INSERT INTO mirror_state (id, saved_at, state_json) VALUES (1, ?, ?) "
#|                 "ON CONFLICT(id) DO UPDATE SET saved_at = excluded.saved_at, "
#|                 "state_json = excluded.state_json",
#|                 (now, json.dumps(state, separators=(",", ":"))))
#| def delete_match(conn: sqlite3.Connection, match_id: str) -> None:
#|     """Drop a match and the saved accumulator (an abandoned empty lobby:"""
#|     with conn:
#|         _delete_match_rows(conn, match_id)
#|         conn.execute("DELETE FROM match WHERE match_id = ?", (match_id,))
#|         conn.execute("DELETE FROM mirror_state")
#| def load_state(conn: sqlite3.Connection) -> dict[str, Any] | None:
#|     """The saved running-match state, or None (none saved / unreadable)."""
#|     row = conn.execute("SELECT state_json FROM mirror_state WHERE id = 1").fetchone()
#|     if not row:
#|         return None
#|     try:
#|         state = json.loads(row[0])
#|     except ValueError:
#|         return None
#|     return state if isinstance(state, dict) else None
#| ===== module: agent.local_mirror =====
#| """agent/local_mirror.py -- every snapshot into player-stats.sqlite."""
#| from __future__ import annotations
#| import hashlib
#| import logging
#| import re
#| import time
#| from datetime import datetime, timedelta, timezone
#| from pathlib import Path
#| from typing import Any, Callable
#| from agent import local_db
#| _HEX = re.compile(r"^[0-9a-fA-F]+$")
#| def match_tag(match_id):
#|     """The 8-hex-digit tag central puts in replay file names (replay_format.match_tag; a test"""
#|     cleaned = (match_id or "").strip().replace("-", "")
#|     return cleaned[:8].lower() if cleaned and _HEX.match(cleaned) else ""
#| logger = logging.getLogger("squad_replay")
#| PREMATCH_MAX_WAIT_S = 600.0   # central's REPLAY_PREMATCH_MAX_WAIT_S
#| FLUSH_INTERVAL_S = 60.0
#| _PRE_MATCH = ("Staging", "WaitingToStart")
#| _POST_MATCH = ("WaitingPostMatch", "LeavingMap", "EndMatch")
#| def _is_skipped_map(map_name: str) -> bool:
#|     return "Jensen" in map_name or map_name == "Jensen's Training Range"
#| def _iso(ts: float) -> str:
#|     return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
#| class LocalMirror:
#|     """Feeds snapshots into player-stats.sqlite (see module docstring)."""
#|     def __init__(self, path: str | Path, *, server_id: str | None = None,
#|                  clock: Callable[[], float] = time.time,
#|                  flush_interval_s: float = FLUSH_INTERVAL_S):
#|         self._path = Path(path)
#|         self._server_id = server_id
#|         self._clock = clock
#|         self._flush_interval_s = flush_interval_s
#|         self._ms = None              # match_stats, imported on first use
#|         self._conn = None
#|         self._off = False            # gave up (no match_stats / no db)
#|         self._resume_checked = False
#|         # The open match: its accumulator and what its rows are keyed by.
#|         self._acc = None
#|         self._match_id: str | None = None
#|         self._started_ts: float | None = None
#|         self._pre_since: float | None = None
#|         self._last_flush = 0.0
#|         self._errors = 0
#|     # -- public ----------------------------------------------------------
#|     def observe(self, snapshot: dict[str, Any]) -> None:
#|         """Fold one snapshot in; never raises."""
#|         if self._off:
#|             return
#|         try:
#|             if not self._ready():
#|                 return
#|             self._observe(snapshot)
#|         except Exception:  # noqa: BLE001 -- the mirror must not stop the agent
#|             self._errors += 1
#|             if self._errors in (1, 10) or self._errors % 100 == 0:
#|                 logger.exception("local stats mirror: snapshot not recorded (%d)",
#|                                  self._errors)
#|     def close(self) -> None:
#|         """Save the running match so the next start resumes it."""
#|         try:
#|             if self._acc is not None and self._conn is not None:
#|                 self._flush(complete=False)
#|         except Exception:  # noqa: BLE001
#|             logger.exception("local stats mirror: final save failed")
#|         finally:
#|             if self._conn is not None:
#|                 try:
#|                     self._conn.close()
#|                 except Exception:  # noqa: BLE001
#|                     pass
#|                 self._conn = None
#|     # -- internals -------------------------------------------------------
#|     def _ready(self) -> bool:
#|         if self._conn is not None:
#|             return True
#|         try:
#|             import match_stats  # the read payload's; absent in older payloads
#|         except ImportError:
#|             logger.info("local stats mirror off: this read payload has no "
#|                         "match_stats (player-stats.sqlite not updated)")
#|             self._off = True
#|             return False
#|         try:
#|             conn = local_db.open_db(self._path)
#|         except Exception as exc:  # noqa: BLE001
#|             logger.warning("local stats mirror off: cannot open %s (%s)",
#|                            self._path, exc)
#|             self._off = True
#|             return False
#|         self._ms = match_stats
#|         self._conn = conn
#|         logger.info("local stats mirror -> %s", self._path)
#|         return True
#|     def _resume(self) -> None:
#|         """Pick up the match an earlier run of the agent saved."""
#|         self._resume_checked = True
#|         saved = local_db.load_state(self._conn)
#|         if not saved:
#|             return
#|         try:
#|             acc = self._ms.MatchAccumulator.from_state(saved["acc"])
#|             match_id = saved["match_id"]
#|             started_ts = float(saved["started_ts"])
#|             pre_since = saved.get("pre_since")
#|         except (KeyError, TypeError, ValueError):
#|             logger.warning("local stats mirror: saved match state unreadable, discarded")
#|             return
#|         self._acc = acc
#|         self._match_id = match_id
#|         self._started_ts = started_ts
#|         self._pre_since = None if pre_since is None else float(pre_since)
#|         self._last_flush = self._clock()
#|         logger.info("local stats mirror: resumed match %s (%d snapshots)",
#|                     match_id, acc.snap_count)
#|     def _observe(self, snap: dict[str, Any]) -> None:
#|         if not self._resume_checked:
#|             self._resume()
#|         gi = snap.get("gameInfo") or {}
#|         state = gi.get("matchState") or ""
#|         map_name = gi.get("mapName") or ""
#|         skipped = _is_skipped_map(map_name)
#|         pre = state in _PRE_MATCH
#|         now = self._clock()
#|         close_after = False
#|         if self._acc is not None and skipped:
#|             self._finish()                        # closed without this snapshot
#|         elif (self._acc is not None and self._pre_since is not None and pre
#|               and now - self._pre_since > PREMATCH_MAX_WAIT_S):
#|             local_db.delete_match(self._conn, self._match_id)
#|             self._clear()
#|         elif self._acc is not None and state in _POST_MATCH:
#|             close_after = True
#|             self._pre_since = None
#|         elif self._acc is not None and state == "InProgress" and self._pre_since is not None:
#|             self._pre_since = None
#|         if self._acc is None and (state == "InProgress" or pre) and not skipped:
#|             self._open(gi, pre, now)
#|         if self._acc is None:
#|             return
#|         self._acc.update(snap)
#|         if close_after:
#|             self._finish()
#|         elif now - self._last_flush >= self._flush_interval_s:
#|             self._flush(complete=False)
#|     def _open(self, gi: dict[str, Any], pre: bool, now: float) -> None:
#|         self._acc = self._ms.MatchAccumulator()
#|         self._started_ts = now
#|         self._match_id = match_tag(gi.get("matchId")) or hashlib.sha1(
#|             f"{_iso(now)}|{gi.get('mapName') or ''}".encode("utf-8")).hexdigest()[:8]
#|         self._pre_since = now if pre else None
#|         self._last_flush = now
#|     def _flush(self, *, complete: bool) -> None:
#|         try:
#|             result = self._acc.finalize()
#|         except ValueError:                        # nothing folded in yet
#|             return
#|         now = self._clock()
#|         duration = result["match"]["duration_s"] or 0
#|         state = None if complete else {
#|             "acc": self._acc.to_state(),
#|             "match_id": self._match_id,
#|             "started_ts": self._started_ts,
#|             "pre_since": self._pre_since,
#|         }
#|         t0 = time.monotonic()
#|         local_db.write_match(
#|             self._conn,
#|             match_id=self._match_id,
#|             server_id=self._server_id,
#|             started_at=_iso(self._started_ts),
#|             ended_at=(datetime.fromtimestamp(self._started_ts, tz=timezone.utc)
#|                       + timedelta(seconds=duration)).isoformat(timespec="seconds"),
#|             result=result,
#|             complete=complete,
#|             now=_iso(now),
#|             state=state,
#|         )
#|         took = time.monotonic() - t0
#|         if took > 1.0:
#|             logger.warning("local stats mirror: flush took %.1fs", took)
#|         self._last_flush = now
#|     def _finish(self) -> None:
#|         self._flush(complete=True)
#|         if complete_id := self._match_id:
#|             logger.info("local stats mirror: match %s recorded", complete_id)
#|         self._clear()
#|     def _clear(self) -> None:
#|         self._acc = None
#|         self._match_id = None
#|         self._started_ts = None
#|         self._pre_since = None
#| ===== module: agent.memory_backend =====
#| """agent/memory_backend.py — Linux process-memory backend (pymem-compatible)."""
#| from __future__ import annotations
#| import ctypes
#| import ctypes.util
#| import logging
#| import os
#| from pathlib import Path
#| logger = logging.getLogger("squad_agent.backend.linux")
#| class MemoryReadError(Exception):
#|     """Raised on any read failure: unmapped address, dead process,"""
#| # pymem-shaped exception module so ``pymem.exception.MemoryReadError``
#| class _exception_module:  # noqa: N801 — naming mirrors pymem.exception
#|     MemoryReadError = MemoryReadError
#| exception = _exception_module()
#| # ---------------------------------------------------------------------------
#| _libc_path = ctypes.util.find_library("c") or "libc.so.6"
#| _libc = ctypes.CDLL(_libc_path, use_errno=True)
#| class _IoVec(ctypes.Structure):
#|     _fields_ = (
#|         ("iov_base", ctypes.c_void_p),
#|         ("iov_len",  ctypes.c_size_t),
#|     )
#| try:
#|     _process_vm_readv = _libc.process_vm_readv
#|     _process_vm_readv.argtypes = (
#|         ctypes.c_int,                  # pid
#|         ctypes.POINTER(_IoVec),        # local iov
#|         ctypes.c_ulong,                # liovcnt
#|         ctypes.POINTER(_IoVec),        # remote iov
#|         ctypes.c_ulong,                # riovcnt
#|         ctypes.c_ulong,                # flags (always 0)
#|     )
#|     _process_vm_readv.restype = ctypes.c_ssize_t
#|     _HAVE_PVR = True
#| except AttributeError:
#|     _process_vm_readv = None
#|     _HAVE_PVR = False
#|     logger.warning("data channel unavailable; using fallback path")
#| # ---------------------------------------------------------------------------
#| def _normalize_image(image: str | None) -> str:
#|     """Strip a legacy ``.exe`` suffix so callers can pass either spelling."""
#|     if not image:
#|         return "SquadGameServer"
#|     n = image.strip()
#|     if n.lower().endswith(".exe"):
#|         n = n[:-4]
#|     return n
#| def _find_pid_for_image(image: str) -> int | None:
#|     """Walk /proc/* and match ``comm`` (kernel-truncated to 15 chars)"""
#|     target = _normalize_image(image)
#|     target_lc = target.lower()
#|     # Linux truncates `comm` (TASK_COMM_LEN = 16, 15 + NUL); compare
#|     target_comm = target_lc[:15]
#|     candidates: list[int] = []
#|     try:
#|         for entry in Path("/proc").iterdir():
#|             name = entry.name
#|             if not name.isdigit():
#|                 continue
#|             pid = int(name)
#|             # Prefer matching the actual exe path (full name) and
#|             exe_match = False
#|             try:
#|                 exe = os.readlink(entry / "exe")
#|                 if target_lc in exe.lower():
#|                     exe_match = True
#|             except OSError:
#|                 pass
#|             comm_match = False
#|             if not exe_match:
#|                 try:
#|                     comm = (entry / "comm").read_text().strip().lower()
#|                     if comm == target_lc or comm == target_comm:
#|                         comm_match = True
#|                 except OSError:
#|                     continue
#|             if exe_match or comm_match:
#|                 candidates.append(pid)
#|     except OSError as exc:
#|         logger.warning("failed to scan /proc: %s", exc)
#|         return None
#|     return min(candidates) if candidates else None
#| def _resolve_base_address(pid: int, image: str) -> int:
#|     """Pick the binary's image-base mapping from /proc/<pid>/maps."""
#|     target = _normalize_image(image).lower()
#|     first_for_target: int | None = None
#|     try:
#|         with open(f"/proc/{pid}/maps", "r", encoding="utf-8") as f:
#|             for line in f:
#|                 parts = line.split(maxsplit=5)
#|                 if len(parts) < 6:
#|                     continue
#|                 addr_range, _perms, _off, _dev, _inode, path = parts
#|                 base = path.strip().rsplit("/", 1)[-1].lower()
#|                 if not base:
#|                     continue
#|                 if base == target or base.startswith(target):
#|                     first_for_target = int(addr_range.split("-")[0], 16)
#|                     break
#|     except OSError as exc:
#|         raise OSError(f"cannot read /proc/{pid}/maps: {exc}") from exc
#|     if first_for_target is not None:
#|         return first_for_target
#|     # Fallback: first executable mapping at all (some Squad builds
#|     try:
#|         with open(f"/proc/{pid}/maps", "r", encoding="utf-8") as f:
#|             for line in f:
#|                 parts = line.split()
#|                 if len(parts) < 2:
#|                     continue
#|                 if "x" in parts[1]:
#|                     return int(parts[0].split("-")[0], 16)
#|     except OSError:
#|         pass
#|     return 0
#| # ---------------------------------------------------------------------------
#| class Pymem:
#|     """Linux equivalent of ``pymem.Pymem`` — same constructor +"""
#|     def __init__(self, image: str | None = None) -> None:
#|         self.process_id: int | None = None
#|         self.process_handle = None    # parity with pymem
#|         self.base_address: int = 0
#|         self._image: str = _normalize_image(image)
#|         if image:
#|             pid = _find_pid_for_image(self._image)
#|             if not pid:
#|                 raise OSError(
#|                     f"process not found: {self._image} (no /proc match)"
#|                 )
#|             self.open_process_from_id(pid)
#|     def open_process_from_id(self, pid: int) -> None:
#|         pid = int(pid)
#|         # Smoke-test access — process_vm_readv on /proc/<pid>/status
#|         if not Path(f"/proc/{pid}").is_dir():
#|             raise OSError(f"no such pid: {pid}")
#|         self.process_id = pid
#|         self.process_handle = pid  # same int — used as handle by callers
#|         self.base_address = _resolve_base_address(pid, self._image)
#|     def read_bytes(self, address: int, size: int) -> bytes:
#|         if self.process_id is None:
#|             raise MemoryReadError("not attached to a process")
#|         if size <= 0:
#|             return b""
#|         if _HAVE_PVR:
#|             buf = (ctypes.c_char * size)()
#|             local = _IoVec(ctypes.cast(buf, ctypes.c_void_p), size)
#|             remote = _IoVec(ctypes.c_void_p(address), size)
#|             n = _process_vm_readv(
#|                 self.process_id,
#|                 ctypes.byref(local), 1,
#|                 ctypes.byref(remote), 1,
#|                 0,
#|             )
#|             if n == size:
#|                 return bytes(buf)
#|             err = ctypes.get_errno()
#|             raise MemoryReadError(
#|                 f"process_vm_readv({size}@0x{address:x}) -> n={n} "
#|                 f"errno={err} ({os.strerror(err) if err else 'short read'})"
#|             )
#|         # /proc/<pid>/mem fallback — needs same-UID + ptrace_scope=0
#|         try:
#|             with open(f"/proc/{self.process_id}/mem", "rb", buffering=0) as f:
#|                 f.seek(address)
#|                 data = f.read(size)
#|         except OSError as exc:
#|             raise MemoryReadError(
#|                 f"/proc/{self.process_id}/mem read({size}@0x{address:x}) "
#|                 f"failed: {exc}"
#|             ) from exc
#|         if len(data) != size:
#|             raise MemoryReadError(
#|                 f"/proc/{self.process_id}/mem short read "
#|                 f"({size}@0x{address:x}) got {len(data)}"
#|             )
#|         return data
#|     # process_vm_readv takes at most IOV_MAX (1024 on Linux) remote iovecs.
#|     _BATCH_IOVECS = 1024
#|     def read_u64_batch(self, addresses) -> list:
#|         """Read one little-endian u64 at each address; ``None`` where the"""
#|         addrs = list(addresses)
#|         out: list = [None] * len(addrs)
#|         if not addrs:
#|             return out
#|         if self.process_id is None:
#|             raise MemoryReadError("not attached to a process")
#|         if not _HAVE_PVR:
#|             for i, a in enumerate(addrs):
#|                 try:
#|                     out[i] = int.from_bytes(self.read_bytes(a, 8), "little")
#|                 except MemoryReadError:
#|                     pass
#|             return out
#|         i = 0
#|         while i < len(addrs):
#|             chunk = addrs[i:i + self._BATCH_IOVECS]
#|             k = len(chunk)
#|             buf = (ctypes.c_char * (8 * k))()
#|             base = ctypes.addressof(buf)
#|             local = (_IoVec * k)(*[_IoVec(ctypes.c_void_p(base + 8 * j), 8) for j in range(k)])
#|             remote = (_IoVec * k)(*[_IoVec(ctypes.c_void_p(a), 8) for a in chunk])
#|             n = _process_vm_readv(self.process_id, local, k, remote, k, 0)
#|             if n < 0:
#|                 err = ctypes.get_errno()
#|                 if err == 3:  # ESRCH: the process is gone
#|                     raise MemoryReadError(f"process_vm_readv batch -> errno={err}")
#|                 n = 0
#|             done = n // 8
#|             raw = bytes(buf)
#|             for j in range(done):
#|                 out[i + j] = int.from_bytes(raw[8 * j:8 * j + 8], "little")
#|             # The address at `done` failed (or the call failed outright):
#|             i += done if done == k else done + 1
#|         return out
#| ===== module: agent.memory_write =====
#| """agent/memory_write.py — the agent's ONLY way to write game memory."""
#| from __future__ import annotations
#| import ctypes
#| import os
#| from agent.memory_backend import MemoryReadError, _IoVec, _libc
#| try:
#|     _process_vm_writev = _libc.process_vm_writev
#|     _process_vm_writev.argtypes = (
#|         ctypes.c_int,
#|         ctypes.POINTER(_IoVec),
#|         ctypes.c_ulong,
#|         ctypes.POINTER(_IoVec),
#|         ctypes.c_ulong,
#|         ctypes.c_ulong,
#|     )
#|     _process_vm_writev.restype = ctypes.c_ssize_t
#|     _HAVE_PVW = True
#| except AttributeError:
#|     _process_vm_writev = None
#|     _HAVE_PVW = False
#| def write_bytes(pm, address: int, data: bytes, length: int) -> None:
#|     """Write ``length`` bytes of ``data`` at ``address`` in the process"""
#|     pid = getattr(pm, "process_id", None)
#|     if pid is None:
#|         raise MemoryReadError("not attached to a process")
#|     to_write = data[:length]
#|     size = len(to_write)
#|     if size == 0:
#|         return
#|     if _HAVE_PVW:
#|         buf = (ctypes.c_char * size)(*to_write)
#|         local = _IoVec(ctypes.cast(buf, ctypes.c_void_p), size)
#|         remote = _IoVec(ctypes.c_void_p(address), size)
#|         n = _process_vm_writev(
#|             pid,
#|             ctypes.byref(local), 1,
#|             ctypes.byref(remote), 1,
#|             0,
#|         )
#|         if n == size:
#|             return
#|         err = ctypes.get_errno()
#|         raise MemoryReadError(
#|             f"process_vm_writev({size}@0x{address:x}) -> n={n} "
#|             f"errno={err} ({os.strerror(err) if err else 'short write'})"
#|         )
#|     try:
#|         with open(f"/proc/{pid}/mem", "r+b", buffering=0) as f:
#|             f.seek(address)
#|             written = f.write(to_write)
#|     except OSError as exc:
#|         raise MemoryReadError(
#|             f"/proc/{pid}/mem write({size}@0x{address:x}) failed: {exc}"
#|         ) from exc
#|     if written != size:
#|         raise MemoryReadError(
#|             f"/proc/{pid}/mem short write ({size}@0x{address:x}) wrote {written}"
#|         )
#| ===== module: agent.offset_client =====
#| """agent/offset_client.py — Agent-side offset fetch client."""
#| from __future__ import annotations
#| import base64
#| import json
#| import logging
#| import secrets
#| import time
#| import urllib.error
#| import urllib.request
#| from typing import Any
#| from ingest import protocol as ingest_protocol
#| from ingest.crypto import CryptoError, EncryptedEnvelope
#| from ingest.offsets import open_response_envelope
#| logger = logging.getLogger("SquadReplay")
#| class OffsetFetchError(Exception):
#|     """Raised when the bundle cannot be fetched / verified. Non-fatal;"""
#| def _b64url_decode(s: str) -> bytes:
#|     """Tolerant base64url decode — server strips padding so the client"""
#|     if not isinstance(s, str):
#|         raise ValueError("base64url field must be a string")
#|     pad = "=" * (-len(s) % 4)
#|     return base64.urlsafe_b64decode(s + pad)
#| def fetch_offsets(
#|     *,
#|     base_url: str,
#|     agent_id: str,
#|     agent_secret: bytes,
#|     timeout: float = 10.0,
#| ) -> dict[str, Any]:
#|     """Request and return the offset bundle as a plain dict."""
#|     url = base_url.rstrip("/") + "/agent/offsets"
#|     # Use a random seq — the server doesn't enforce monotonicity on
#|     seq = secrets.randbits(31)
#|     ts = int(time.time())
#|     # Advertise the host platform so central can pick a matching
#|     import sys as _sys
#|     agent_platform = "linux" if _sys.platform.startswith("linux") else _sys.platform
#|     req_body = ingest_protocol.encode_envelope(
#|         agent_id=agent_id,
#|         seq=seq,
#|         agent_secret=agent_secret,
#|         snapshot_json=json.dumps({
#|             "want": "offsets",
#|             "platform": agent_platform,
#|         }).encode("utf-8"),
#|         ts=ts,
#|     )
#|     req = urllib.request.Request(
#|         url,
#|         data=req_body,
#|         # User-Agent matters: Cloudflare's bot protection 403s the
#|         headers={
#|             "Content-Type": "application/json",
#|             "User-Agent":   "SquadReplay/1.0",
#|         },
#|         method="POST",
#|     )
#|     try:
#|         with urllib.request.urlopen(req, timeout=timeout) as resp:
#|             raw = resp.read()
#|     except urllib.error.HTTPError as e:
#|         raise OffsetFetchError(f"HTTP {e.code} from central") from e
#|     except (urllib.error.URLError, TimeoutError, OSError) as e:
#|         raise OffsetFetchError(f"transport error: {e}") from e
#|     try:
#|         doc = json.loads(raw)
#|         nonce = _b64url_decode(doc["nonce"])
#|         ciphertext = _b64url_decode(doc["ciphertext"])
#|     except (json.JSONDecodeError, KeyError, ValueError) as e:
#|         raise OffsetFetchError(f"bad response shape: {e}") from e
#|     env = EncryptedEnvelope(nonce=nonce, ciphertext=ciphertext)
#|     try:
#|         plaintext = open_response_envelope(
#|             agent_secret,
#|             env,
#|             agent_id=agent_id,
#|             seq=seq,
#|             ts=ts,
#|         )
#|     except CryptoError as e:
#|         raise OffsetFetchError(f"response decrypt failed: {e}") from e
#|     try:
#|         bundle = json.loads(plaintext)
#|     except (json.JSONDecodeError, ValueError) as e:
#|         raise OffsetFetchError(f"bundle not json: {e}") from e
#|     if not isinstance(bundle, dict) or not isinstance(bundle.get("offsets"), dict):
#|         raise OffsetFetchError("bundle missing offsets dict")
#|     return bundle
#| def apply_offsets(target_class: Any, bundle: dict[str, Any]) -> list[str]:
#|     """Patch attributes named in ``bundle['offsets']`` onto ``target_class``."""
#|     applied: list[str] = []
#|     offsets = bundle.get("offsets") or {}
#|     target_name = getattr(target_class, "__name__", repr(target_class))
#|     for name, value in offsets.items():
#|         if name.startswith("_"):
#|             continue
#|         if not hasattr(target_class, name):
#|             logger.debug("offset %s not defined on %s — skipping",
#|                          name, target_name)
#|             continue
#|         try:
#|             int_value = int(value)
#|         except (TypeError, ValueError):
#|             logger.warning("config %s has non-int value %r — ignored",
#|                            name, value)
#|             continue
#|         setattr(target_class, name, int_value)
#|         applied.append(name)
#|     return applied
#| __all__ = ["OffsetFetchError", "apply_offsets", "fetch_offsets"]
#| ===== module: agent.payload_client =====
#| """agent/payload_client.py — fetch, verify and install a code payload."""
#| from __future__ import annotations
#| import json
#| import logging
#| import secrets
#| import time
#| import urllib.error
#| import urllib.request
#| from agent.payload_format import PayloadError, verify
#| from agent.payload_loader import PayloadImportError, install
#| from agent.payload_trust import payload_public_key
#| from ingest import protocol as ingest_protocol
#| from ingest.crypto import CryptoError, EncryptedEnvelope
#| from ingest.offsets import open_response_envelope
#| logger = logging.getLogger("SquadReplay")
#| #: A payload is a few hundred KiB; refuse anything absurd before parsing.
#| MAX_RESPONSE_BYTES = 16 * 1024 * 1024
#| class PayloadFetchError(Exception):
#|     """The payload could not be fetched, verified or installed."""
#| def _b64url_decode(s: str) -> bytes:
#|     import base64
#|     if not isinstance(s, str):
#|         raise ValueError("base64url field must be a string")
#|     return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
#| def fetch_payload(
#|     *,
#|     base_url: str,
#|     agent_id: str,
#|     agent_secret: bytes,
#|     kind: str,
#|     have_version: int = 0,
#|     squad_build: str | None = None,
#|     timeout: float = 30.0,
#| ) -> dict:
#|     """Return the payload document central is serving for ``kind``."""
#|     url = base_url.rstrip("/") + "/agent/payload"
#|     seq = secrets.randbits(31)
#|     ts = int(time.time())
#|     body = ingest_protocol.encode_envelope(
#|         agent_id=agent_id,
#|         seq=seq,
#|         agent_secret=agent_secret,
#|         snapshot_json=json.dumps({
#|             "want": "payload",
#|             "kind": kind,
#|             "have_version": int(have_version),
#|             "squad_build": squad_build,
#|         }).encode("utf-8"),
#|         ts=ts,
#|     )
#|     req = urllib.request.Request(
#|         url,
#|         data=body,
#|         # Cloudflare 403s the default urllib banner (see offset_client).
#|         headers={"Content-Type": "application/json",
#|                  "User-Agent": "SquadReplay/1.0"},
#|         method="POST",
#|     )
#|     try:
#|         with urllib.request.urlopen(req, timeout=timeout) as resp:
#|             raw = resp.read(MAX_RESPONSE_BYTES + 1)
#|     except urllib.error.HTTPError as e:
#|         raise PayloadFetchError(f"HTTP {e.code} from central") from e
#|     except (urllib.error.URLError, TimeoutError, OSError) as e:
#|         raise PayloadFetchError(f"transport error: {e}") from e
#|     if len(raw) > MAX_RESPONSE_BYTES:
#|         raise PayloadFetchError("response larger than the payload ceiling")
#|     try:
#|         doc = json.loads(raw)
#|         env = EncryptedEnvelope(nonce=_b64url_decode(doc["nonce"]),
#|                                 ciphertext=_b64url_decode(doc["ciphertext"]))
#|     except (json.JSONDecodeError, KeyError, ValueError) as e:
#|         raise PayloadFetchError(f"bad response shape: {e}") from e
#|     try:
#|         plaintext = open_response_envelope(
#|             agent_secret, env, agent_id=agent_id, seq=seq, ts=ts)
#|     except CryptoError as e:
#|         raise PayloadFetchError(f"response decrypt failed: {e}") from e
#|     try:
#|         inner = json.loads(plaintext)
#|     except (json.JSONDecodeError, ValueError) as e:
#|         raise PayloadFetchError(f"payload not json: {e}") from e
#|     if not isinstance(inner, dict):
#|         raise PayloadFetchError("payload is not an object")
#|     return inner
#| def load_payload(
#|     *,
#|     base_url: str,
#|     agent_id: str,
#|     agent_secret: bytes,
#|     kind: str,
#|     agent_version: str,
#|     have_version: int = 0,
#|     squad_build: str | None = None,
#|     timeout: float = 30.0,
#| ) -> int | None:
#|     """Fetch, verify and install the ``kind`` payload."""
#|     pub = payload_public_key()
#|     if pub is None:
#|         raise PayloadFetchError(
#|             "this build has no payload trust key baked in; refusing to load code")
#|     doc = fetch_payload(
#|         base_url=base_url, agent_id=agent_id, agent_secret=agent_secret,
#|         kind=kind, have_version=have_version, squad_build=squad_build,
#|         timeout=timeout,
#|     )
#|     if doc.get("uptodate"):
#|         return None
#|     try:
#|         modules = verify(
#|             doc, pub,
#|             kind=kind,
#|             min_version=have_version,
#|             agent_version=agent_version,
#|             squad_build=squad_build,
#|         )
#|     except PayloadError as e:
#|         raise PayloadFetchError(f"payload rejected: {e}") from e
#|     version = int(doc["version"])
#|     try:
#|         install(modules, origin=f"{kind} v{version}")
#|     except PayloadImportError as e:
#|         raise PayloadFetchError(f"payload not installable: {e}") from e
#|     logger.info("payload %s v%d installed (%d module(s))",
#|                 kind, version, len(modules))
#|     return version
#| __all__ = ["MAX_RESPONSE_BYTES", "PayloadFetchError", "fetch_payload",
#|            "load_payload"]
#| ===== module: agent.payload_format =====
#| """agent/payload_format.py — the signed code payload, packed and verified."""
#| from __future__ import annotations
#| import base64
#| import json
#| import zlib
#| from agent.signing import SignatureError, verify_manifest
#| #: What a payload can carry. Mirrors agent/capabilities.py's capabilities.
#| PAYLOAD_KINDS = ("read", "write", "voice", "session")
#| #: Wire format version of the envelope itself (not of its contents).
#| PAYLOAD_FORMAT_V = 1
#| #: Decompression ceiling. The payload is signature-verified before it is
#| MAX_MODULES_BYTES = 32 * 1024 * 1024
#| _SIG_FIELD = "signature"
#| class PayloadError(Exception):
#|     """A payload is missing, malformed, not for us, or not trusted."""
#| def _valid_module_name(name: object) -> bool:
#|     """A payload module name must be a plain dotted identifier."""
#|     if not isinstance(name, str) or not name:
#|         return False
#|     parts = name.split(".")
#|     return all(p.isidentifier() for p in parts)
#| def _version_tuple(v: str) -> tuple[int, ...]:
#|     """``"0.85.1"`` -> ``(0, 85, 1)``. Unparseable parts count as 0 so a"""
#|     out = []
#|     for part in str(v).split("."):
#|         digits = "".join(c for c in part if c.isdigit())
#|         out.append(int(digits) if digits else 0)
#|     return tuple(out)
#| def verify(
#|     payload: object,
#|     pub,
#|     *,
#|     kind: str,
#|     min_version: int,
#|     agent_version: str,
#|     squad_build: str | None = None,
#| ) -> dict[str, str]:
#|     """Verify ``payload`` and return its ``{module name: source}``."""
#|     if not isinstance(payload, dict):
#|         raise PayloadError("payload is not an object")
#|     if payload.get("v") != PAYLOAD_FORMAT_V:
#|         raise PayloadError(f"unsupported payload format: {payload.get('v')!r}")
#|     got_kind = payload.get("kind")
#|     if got_kind != kind:
#|         raise PayloadError(f"payload is {got_kind!r}, asked for {kind!r}")
#|     try:
#|         version = int(payload["version"])
#|     except (KeyError, TypeError, ValueError) as exc:
#|         raise PayloadError("payload has no usable version") from exc
#|     if version <= int(min_version):
#|         raise PayloadError(
#|             f"payload version {version} is not newer than {min_version}")
#|     # A build-bound payload (voice: its probe address only exists in one
#|     want_build = payload.get("squad_build")
#|     if want_build is not None and payload.get("build_resolver") is not True:
#|         if squad_build is None:
#|             raise PayloadError("payload is build-bound but our build is unknown")
#|         if str(want_build) != str(squad_build):
#|             raise PayloadError(
#|                 f"payload is for build {want_build!r}, we run {squad_build!r}")
#|     need = payload.get("agent_min_version")
#|     if need and _version_tuple(agent_version) < _version_tuple(need):
#|         raise PayloadError(
#|             f"payload needs agent >= {need}, this is {agent_version}")
#|     # The trust gate. Nothing below this line runs on unverified bytes.
#|     try:
#|         verify_manifest(pub, payload)
#|     except SignatureError as exc:
#|         raise PayloadError(f"signature: {exc}") from exc
#|     try:
#|         packed = base64.b64decode(payload["modules_z"], validate=True)
#|     except (KeyError, TypeError, ValueError) as exc:
#|         raise PayloadError(f"modules_z is not base64: {exc}") from exc
#|     try:
#|         d = zlib.decompressobj()
#|         blob = d.decompress(packed, MAX_MODULES_BYTES)
#|         if d.unconsumed_tail:
#|             raise PayloadError("modules exceed the decompression ceiling")
#|     except zlib.error as exc:
#|         raise PayloadError(f"modules do not decompress: {exc}") from exc
#|     try:
#|         modules = json.loads(blob)
#|     except (json.JSONDecodeError, ValueError) as exc:
#|         raise PayloadError(f"modules are not json: {exc}") from exc
#|     if not isinstance(modules, dict) or not modules:
#|         raise PayloadError("payload carries no modules")
#|     for name, source in modules.items():
#|         if not _valid_module_name(name):
#|             raise PayloadError(f"not a module name: {name!r}")
#|         if not isinstance(source, str):
#|             raise PayloadError(f"source for {name} is not a string")
#|     return modules
#| ===== module: agent.payload_loader =====
#| """agent/payload_loader.py — import a verified payload's modules."""
#| from __future__ import annotations
#| import importlib.abc
#| import importlib.machinery
#| import importlib.util
#| import logging
#| import sys
#| import types
#| logger = logging.getLogger("squad_agent.payload")
#| #: Module names this process installed from a payload, in install order.
#| _INSTALLED: dict[str, str] = {}
#| class PayloadImportError(Exception):
#|     """A payload's modules could not be installed or imported."""
#| class _PayloadFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
#|     """Serves exactly the module names a payload declared, from memory."""
#|     def __init__(self, sources: dict[str, str], origin: str):
#|         self._sources = dict(sources)
#|         self._origin = origin
#|     # -- MetaPathFinder --------------------------------------------------
#|     def find_spec(self, fullname, path=None, target=None):
#|         if fullname not in self._sources:
#|             return None
#|         spec = importlib.machinery.ModuleSpec(
#|             fullname, self, origin=f"<squadreplay payload {self._origin}>")
#|         spec.has_location = False
#|         return spec
#|     # -- Loader ----------------------------------------------------------
#|     def create_module(self, spec):
#|         return None          # default module object
#|     def exec_module(self, module: types.ModuleType) -> None:
#|         name = module.__name__
#|         source = self._sources[name]
#|         # Compile first: a syntax error then surfaces before any of the
#|         code = compile(source, module.__spec__.origin, "exec")
#|         exec(code, module.__dict__)
#|     def names(self) -> tuple[str, ...]:
#|         return tuple(sorted(self._sources))
#| def install(modules: dict[str, str], *, origin: str = "payload") -> tuple[str, ...]:
#|     """Make ``modules`` importable. Returns the names installed."""
#|     if not modules:
#|         raise PayloadImportError("payload carries no modules")
#|     clashes = [
#|         n for n in modules
#|         if n in sys.modules and n not in _INSTALLED
#|     ]
#|     if clashes:
#|         raise PayloadImportError(
#|             "payload would shadow already-imported module(s): "
#|             + ", ".join(sorted(clashes))
#|         )
#|     # Replacing our own earlier payload: drop the old modules so the
#|     for name in modules:
#|         if name in _INSTALLED:
#|             sys.modules.pop(name, None)
#|     finder = _PayloadFinder(modules, origin)
#|     sys.meta_path.insert(0, finder)
#|     for name in modules:
#|         _INSTALLED[name] = origin
#|     logger.info("payload %s: %d module(s) available (%s)",
#|                 origin, len(modules), ", ".join(finder.names()))
#|     return finder.names()
#| def installed() -> dict[str, str]:
#|     """``{module name: origin}`` for everything a payload installed."""
#|     return dict(_INSTALLED)
#| __all__ = ["PayloadImportError", "install", "installed"]
#| ===== module: agent.payload_trust =====
#| """agent/payload_trust.py — the public key payloads are verified against."""
#| from __future__ import annotations
#| #: Base64 of the raw 32-byte Ed25519 public key.
#| EMBEDDED_PAYLOAD_PUBKEY_B64: str = "wz/e9lMcF40/+TCFR75g4Up6sC+f4gDthy7vQrA1VWg="
#| def payload_public_key():
#|     """The baked trust anchor, or ``None`` when this build has none."""
#|     if not EMBEDDED_PAYLOAD_PUBKEY_B64:
#|         return None
#|     from agent.signing import load_public_key_from_b64
#|     return load_public_key_from_b64(EMBEDDED_PAYLOAD_PUBKEY_B64)
#| __all__ = ["EMBEDDED_PAYLOAD_PUBKEY_B64", "payload_public_key"]
#| ===== module: agent.queue_priority_client =====
#| """agent/queue_priority_client.py — Agent-side queue-priority fetch client."""
#| from __future__ import annotations
#| import json
#| import secrets
#| import time
#| import urllib.error
#| import urllib.request
#| from typing import Any
#| from ingest import protocol as ingest_protocol
#| from ingest.crypto import CryptoError, EncryptedEnvelope
#| from ingest.offsets import open_response_envelope
#| class QueuePriorityFetchError(Exception):
#|     """Raised when the config cannot be fetched / verified. Non-fatal;"""
#| def _b64url_decode(s: str) -> bytes:
#|     if not isinstance(s, str):
#|         raise ValueError("base64url field must be a string")
#|     pad = "=" * (-len(s) % 4)
#|     import base64
#|     return base64.urlsafe_b64decode(s + pad)
#| def fetch_queue_priority(
#|     *,
#|     base_url: str,
#|     agent_id: str,
#|     agent_secret: bytes,
#|     timeout: float = 10.0,
#| ) -> dict[str, Any]:
#|     """Request the resolved queue-priority state for this agent's community."""
#|     url = base_url.rstrip("/") + "/agent/queue_priority"
#|     seq = secrets.randbits(31)
#|     ts = int(time.time())
#|     req_body = ingest_protocol.encode_envelope(
#|         agent_id=agent_id,
#|         seq=seq,
#|         agent_secret=agent_secret,
#|         snapshot_json=json.dumps({"want": "queue_priority"}).encode("utf-8"),
#|         ts=ts,
#|     )
#|     req = urllib.request.Request(
#|         url,
#|         data=req_body,
#|         headers={
#|             "Content-Type": "application/json",
#|             "User-Agent":   "SquadReplay/1.0",
#|         },
#|         method="POST",
#|     )
#|     try:
#|         with urllib.request.urlopen(req, timeout=timeout) as resp:
#|             raw = resp.read()
#|     except urllib.error.HTTPError as e:
#|         raise QueuePriorityFetchError(f"HTTP {e.code} from central") from e
#|     except (urllib.error.URLError, TimeoutError, OSError) as e:
#|         raise QueuePriorityFetchError(f"transport error: {e}") from e
#|     try:
#|         doc = json.loads(raw)
#|         nonce = _b64url_decode(doc["nonce"])
#|         ciphertext = _b64url_decode(doc["ciphertext"])
#|     except (json.JSONDecodeError, KeyError, ValueError) as e:
#|         raise QueuePriorityFetchError(f"bad response shape: {e}") from e
#|     env = EncryptedEnvelope(nonce=nonce, ciphertext=ciphertext)
#|     try:
#|         plaintext = open_response_envelope(
#|             agent_secret,
#|             env,
#|             agent_id=agent_id,
#|             seq=seq,
#|             ts=ts,
#|         )
#|     except CryptoError as e:
#|         raise QueuePriorityFetchError(f"response decrypt failed: {e}") from e
#|     try:
#|         doc = json.loads(plaintext)
#|     except (json.JSONDecodeError, ValueError) as e:
#|         raise QueuePriorityFetchError(f"config not json: {e}") from e
#|     if not isinstance(doc, dict) or 'enabled' not in doc:
#|         raise QueuePriorityFetchError("response missing 'enabled'")
#|     return {
#|         'enabled': bool(doc.get('enabled')),
#|         'reservet1': [e for e in (doc.get('reservet1') or []) if isinstance(e, str)],
#|         'reservet2': [e for e in (doc.get('reservet2') or []) if isinstance(e, str)],
#|     }
#| __all__ = ["QueuePriorityFetchError", "fetch_queue_priority"]
#| ===== module: agent.secret_store =====
#| """agent/secret_store.py — Cross-platform secret storage for the agent."""
#| from __future__ import annotations
#| import logging
#| import os
#| from pathlib import Path
#| logger = logging.getLogger("SquadReplay")
#| _SYSTEMD_CREDS_PREFIX = "systemd-creds:"
#| class SecretStoreError(Exception):
#|     """Raised when an explicitly-protected value fails to decrypt."""
#| def load_secret_from_env_value(value: str) -> str:
#|     """Return the plaintext hex string from whatever shape the env"""
#|     if not value:
#|         return ""
#|     stripped = value.strip()
#|     # --- systemd-creds path -----------------------------------------
#|     if stripped.startswith(_SYSTEMD_CREDS_PREFIX):
#|         name = stripped[len(_SYSTEMD_CREDS_PREFIX):].strip()
#|         if not name:
#|             raise SecretStoreError("systemd-creds: reference is empty")
#|         creds_dir = os.environ.get("CREDENTIALS_DIRECTORY")
#|         if not creds_dir:
#|             raise SecretStoreError(
#|                 "CREDENTIALS_DIRECTORY env not set — systemd must spawn "
#|                 "the agent via LoadCredentialEncrypted="
#|             )
#|         cred_path = Path(creds_dir) / name
#|         try:
#|             data = cred_path.read_text(encoding="utf-8").strip()
#|         except OSError as exc:
#|             raise SecretStoreError(f"systemd-creds read {cred_path} failed: {exc}") from exc
#|         if not data:
#|             raise SecretStoreError(f"systemd-creds {cred_path} is empty")
#|         return data
#|     # --- Plain hex ------------------------------------------------
#|     return stripped
#| def protect_to_storage_string(plaintext: str) -> str:
#|     """Return the at-rest representation of ``plaintext`` for this host."""
#|     return plaintext
#| def protection_available() -> bool:
#|     """True when the host supports at-rest encryption beyond"""
#|     return bool(os.environ.get("CREDENTIALS_DIRECTORY"))
#| __all__ = [
#|     "SecretStoreError",
#|     "load_secret_from_env_value",
#|     "protect_to_storage_string",
#|     "protection_available",
#| ]
#| ===== module: agent.signing =====
#| """agent/signing.py — trust anchor for binary auto-update."""
#| from __future__ import annotations
#| import base64
#| import json
#| from cryptography.exceptions import InvalidSignature
#| from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
#| class SignatureError(Exception):
#|     """Raised when a manifest signature is missing, malformed, or"""
#| def load_public_key_from_b64(b64_raw: str) -> Ed25519PublicKey:
#|     """Public key embedded in the agent is stored as base64-encoded raw"""
#|     raw = base64.b64decode(b64_raw)
#|     return Ed25519PublicKey.from_public_bytes(raw)
#| def verify_manifest(pub: Ed25519PublicKey, manifest: dict) -> None:
#|     """Raise :class:`SignatureError` unless the manifest's embedded"""
#|     sig_b64 = manifest.get("signature")
#|     if not isinstance(sig_b64, str) or not sig_b64:
#|         raise SignatureError("manifest missing signature field")
#|     try:
#|         sig = base64.b64decode(sig_b64)
#|     except (ValueError, TypeError) as exc:
#|         raise SignatureError(f"bad base64 in signature: {exc}") from exc
#|     body = {k: v for k, v in manifest.items() if k != "signature"}
#|     canonical = json.dumps(
#|         body, sort_keys=True, ensure_ascii=False, separators=(",", ":")
#|     ).encode("utf-8")
#|     try:
#|         pub.verify(sig, canonical)
#|     except InvalidSignature as exc:
#|         raise SignatureError("signature does not verify") from exc
#| ===== module: agent.updater =====
#| """agent/updater.py — fetch, verify, self-replace."""
#| from __future__ import annotations
#| import hashlib
#| import json
#| import logging
#| import os
#| import subprocess
#| import urllib.error
#| import urllib.parse
#| import urllib.request
#| from pathlib import Path
#| from typing import Any
#| from agent.signing import SignatureError, load_public_key_from_b64, verify_manifest
#| logger = logging.getLogger("SquadReplay")
#| # -----------------------------------------------------------------------
#| _EMBEDDED_PUBLIC_KEY_B64 = "icsYlNSqhAir5GeHxnuou/czdXc9qnChGSBXBlyexiU="
#| # Reported by the agent and compared against the manifest. Bump this on
#| AGENT_VERSION = "0.87.2"
#| # Where packaged agents push snapshots + fetch manifests / offsets.
#| _BAKED_PUSH_URL = "https://squadreplay.com"
#| # How often the background updater checks. 5 min is the production
#| CHECK_INTERVAL_SECONDS = 5 * 60   # 5 min — matches CLAUDE.md "auto-update propagation" note
#| # Where we persist the last-seen version number (downgrade guard) and
#| def _is_packaged() -> bool:
#|     # A downloaded single-file variant (agent/_runtime.py) is as "installed
#|     from agent import _runtime
#|     if _runtime.is_bundle():
#|         return True
#|     return False
#| def _install_root() -> Path:
#|     """Where ``.new`` should land + where the swap helper should put the"""
#|     # A single-file variant lives wherever it was put; that is its root.
#|     from agent import _runtime
#|     _bundle = _runtime.bundle_path()
#|     if _bundle is not None:
#|         return _bundle.resolve().parent
#|     return Path.cwd()
#| _MAX_BINARY_BYTES = 200 * 1024 * 1024  # 200 MB cap — agent binaries are ~30 MB
#| def _current_binary_sha() -> str:
#|     """SHA-256 of the currently running agent binary as lower-case hex."""
#|     try:
#|         path = _install_root() / _current_exe_name()
#|         if not path.is_file():
#|             return ""
#|         h = hashlib.sha256()
#|         with path.open("rb") as f:
#|             # Streamed read keeps memory flat for the ~30 MB binary.
#|             for chunk in iter(lambda: f.read(64 * 1024), b""):
#|                 h.update(chunk)
#|         return h.hexdigest()
#|     except (OSError, ValueError):
#|         return ""
#| class UpdateError(Exception):
#|     """Generic update failure. The caller logs and continues — never"""
#| # -----------------------------------------------------------------------
#| def _parse_version(v: str) -> tuple[int, ...]:
#|     """Very forgiving semver parser. Non-numeric suffixes are ignored;"""
#|     parts: list[int] = []
#|     for chunk in v.split("."):
#|         num = ""
#|         for ch in chunk:
#|             if ch.isdigit():
#|                 num += ch
#|             else:
#|                 break
#|         if not num:
#|             break
#|         parts.append(int(num))
#|     return tuple(parts) or (0,)
#| def is_newer(candidate: str, current: str) -> bool:
#|     return _parse_version(candidate) > _parse_version(current)
#| # -----------------------------------------------------------------------
#| def _platform_tag() -> str:
#|     """Map sys.platform to the manifest routing token the central"""
#|     from agent import _runtime
#|     if _runtime.is_bundle():
#|         from agent import capabilities
#|         from ingest.variants import bundle_platform
#|         return bundle_platform(capabilities.variant_name())
#|     return "linux"
#| def _fetch_manifest(base_url: str, timeout: float = 10.0) -> dict[str, Any]:
#|     # Send platform=linux so central can route to the right binary.
#|     url = (base_url.rstrip("/")
#|            + "/agent/manifest?platform="
#|            + urllib.parse.quote(_platform_tag(), safe=""))
#|     req = urllib.request.Request(url, headers={"User-Agent": f"SquadReplay/{AGENT_VERSION} ({_platform_tag()})"})
#|     try:
#|         with urllib.request.urlopen(req, timeout=timeout) as resp:
#|             raw = resp.read(256 * 1024)   # manifest is tiny
#|     except (urllib.error.URLError, urllib.error.HTTPError,
#|             TimeoutError, OSError) as exc:
#|         raise UpdateError(f"manifest fetch failed: {exc}") from exc
#|     try:
#|         doc = json.loads(raw)
#|     except (ValueError, json.JSONDecodeError) as exc:
#|         raise UpdateError(f"manifest not json: {exc}") from exc
#|     if not isinstance(doc, dict):
#|         raise UpdateError("manifest is not a json object")
#|     # Safety net: refuse a manifest whose advertised platform doesn't
#|     declared = str(doc.get("platform") or "").strip().lower()
#|     if declared and declared != _platform_tag():
#|         raise UpdateError(
#|             f"manifest platform mismatch: server={declared!r}, agent={_platform_tag()!r}"
#|         )
#|     return doc
#| def _download_binary(url: str, expected_sha256_hex: str,
#|                      timeout: float = 120.0) -> bytes:
#|     # Identify explicitly so Cloudflare bot-mitigation doesn't 403 us —
#|     req = urllib.request.Request(
#|         url, headers={"User-Agent": f"SquadReplay/{AGENT_VERSION} ({_platform_tag()})"},
#|     )
#|     try:
#|         with urllib.request.urlopen(req, timeout=timeout) as resp:
#|             buf = bytearray()
#|             while True:
#|                 chunk = resp.read(64 * 1024)
#|                 if not chunk:
#|                     break
#|                 buf.extend(chunk)
#|                 if len(buf) > _MAX_BINARY_BYTES:
#|                     raise UpdateError("binary exceeds size cap")
#|     except (urllib.error.URLError, urllib.error.HTTPError,
#|             TimeoutError, OSError) as exc:
#|         raise UpdateError(f"binary fetch failed: {exc}") from exc
#|     digest = hashlib.sha256(buf).hexdigest()
#|     if digest.lower() != expected_sha256_hex.lower():
#|         raise UpdateError(
#|             f"binary sha256 mismatch — expected {expected_sha256_hex[:16]}..., "
#|             f"got {digest[:16]}..."
#|         )
#|     return bytes(buf)
#| # -----------------------------------------------------------------------
#| def _current_exe_name() -> str:
#|     """Resolve the running binary's on-disk filename (``SquadReplay``)."""
#|     from agent import _runtime
#|     _bundle = _runtime.bundle_path()
#|     if _bundle is not None:
#|         return _bundle.name
#|     return "SquadReplay"
#| def _write_new_binary(new_bytes: bytes) -> Path:
#|     root = _install_root()
#|     stem = Path(_current_exe_name()).stem
#|     new_path = root / f"{stem}.new"
#|     new_path.write_bytes(new_bytes)
#|     return new_path
#| def _spawn_launcher(new_path: Path) -> None:
#|     """Put the downloaded file in place and arrange the restart; the caller exits afterwards."""
#|     _swap_bundle(new_path)
#| def _swap_bundle(new_path: Path) -> None:
#|     """One-file agent: the new file replaces the running one (which keeps running from memory),"""
#|     cur = _install_root() / _current_exe_name()
#|     bak = cur.with_suffix(".bak")
#|     try:
#|         new_path.chmod(0o755)
#|         if cur.exists():
#|             os.replace(cur, bak)
#|         os.replace(new_path, cur)
#|     except OSError as exc:
#|         if bak.exists() and not cur.exists():
#|             os.replace(bak, cur)                # leave the old agent where it was
#|         raise UpdateError(f"could not replace the agent file: {exc}") from exc
#|     relaunch_later(cur)
#| def relaunch_later(path: Path, delay: int = 2) -> None:
#|     """Start the one-file agent at ``path`` again after ``delay`` seconds, from a detached shell, so the"""
#|     from agent import _runtime
#|     if os.environ.get("SQUAD_AGENT_SUPERVISED"):
#|         return
#|     try:
#|         subprocess.Popen(["/bin/sh", "-c", f'sleep {int(delay)}; exec "$@"', "sh", _runtime.interpreter(), str(path)],
#|                          close_fds=True, start_new_session=True,
#|                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
#|     except (OSError, subprocess.SubprocessError) as exc:
#|         raise UpdateError(f"relaunch failed: {exc}") from exc
#| # -----------------------------------------------------------------------
#| def check_and_apply(base_url: str, *,
#|                     current_version: str = AGENT_VERSION,
#|                     skip_if_pubkey_missing: bool = True) -> bool:
#|     """Run one update-check cycle. Returns True if an update was"""
#|     try:
#|         if not _EMBEDDED_PUBLIC_KEY_B64:
#|             if skip_if_pubkey_missing:
#|                 logger.info("updater disabled: no embedded public key")
#|                 return False
#|             raise UpdateError("updater: embedded public key is empty")
#|         pub = load_public_key_from_b64(_EMBEDDED_PUBLIC_KEY_B64)
#|         logger.info("updater: checking for updates (current=%s)", current_version)
#|         manifest = _fetch_manifest(base_url)
#|         try:
#|             verify_manifest(pub, manifest)
#|         except SignatureError as exc:
#|             raise UpdateError(f"manifest signature invalid: {exc}") from exc
#|         remote_version = str(manifest.get("version") or "")
#|         if not remote_version:
#|             raise UpdateError("manifest missing version")
#|         binary_url = manifest.get("binary_url")
#|         sha256 = manifest.get("sha256")
#|         if not isinstance(binary_url, str) or not isinstance(sha256, str):
#|             raise UpdateError("manifest missing binary_url or sha256")
#|         remote_sha_lc = sha256.lower()
#|         # Decide whether to pull. Three cases:
#|         needs_update = is_newer(remote_version, current_version)
#|         if not needs_update and remote_version == current_version:
#|             local_sha = _current_binary_sha()
#|             if local_sha and local_sha != remote_sha_lc:
#|                 logger.warning(
#|                     "updater: same version (%s) published with a different "
#|                     "binary (local sha=%s..., remote sha=%s...) — pulling "
#|                     "rebuild",
#|                     current_version, local_sha[:12], remote_sha_lc[:12],
#|                 )
#|                 needs_update = True
#|         if not needs_update:
#|             logger.info("updater: up to date (current=%s, remote=%s)",
#|                         current_version, remote_version)
#|             return False
#|         # Downgrade guard — protects against an attacker who replays an
#|         stem = Path(_current_exe_name()).stem
#|         seen_path = _install_root() / f"{stem}.version.lock"
#|         highest = ""
#|         try:
#|             highest = seen_path.read_text(encoding="utf-8").strip()
#|         except (FileNotFoundError, OSError):
#|             pass
#|         if highest and is_newer(highest, remote_version):
#|             raise UpdateError(
#|                 f"downgrade blocked: seen {highest}, remote {remote_version}")
#|         logger.info("updater: applying update %s", remote_version)
#|         new_bytes = _download_binary(binary_url, sha256)
#|         new_path = _write_new_binary(new_bytes)
#|         try:
#|             seen_path.write_text(remote_version + "\n", encoding="utf-8")
#|         except OSError as exc:
#|             logger.warning("updater: could not persist version lock: %s", exc)
#|         _spawn_launcher(new_path)
#|         logger.info("updater: restarting to apply %s", remote_version)
#|         return True
#|     except UpdateError as exc:
#|         logger.warning("updater: %s", exc)
#|         return False
#|     except Exception as exc:  # pragma: no cover  # defensive catch-all
#|         logger.warning("updater: unexpected failure: %s", exc)
#|         return False
#| def run_background(base_url: str, stop_event=None) -> None:
#|     """Blocking loop — kick from a dedicated thread. Calls"""
#|     import threading
#|     if stop_event is None:
#|         stop_event = threading.Event()
#|     # First check runs ~60s after boot so we don't thrash the network
#|     if stop_event.wait(60):
#|         return
#|     while not stop_event.is_set():
#|         if check_and_apply(base_url):
#|             os._exit(0)   # helper is rotating; don't let anything else intervene
#|         if CHECK_INTERVAL_SECONDS <= 0:
#|             return
#|         if stop_event.wait(CHECK_INTERVAL_SECONDS):
#|             return
#| __all__ = [
#|     "AGENT_VERSION",
#|     "CHECK_INTERVAL_SECONDS",
#|     "UpdateError",
#|     "check_and_apply",
#|     "is_newer",
#|     "run_background",
#| ]
#| ===== module: agent.voice_enricher =====
#| """voice-enricher -- the unprivileged half of the voice subsystem."""
#| import collections
#| import glob
#| import os
#| import socket
#| import struct
#| import threading
#| import time
#| from voice.ogg_opus import ogg_opus_mux
#| from voice.sender_map import SenderMap
#| from voice.track import VoiceTrack
#| from voice.utterances import group_utterances
#| _FRAME = struct.Struct("<QIBBBB64s")   # sender, seq, ch, flag, len, pad, data[64]
#| _READ_ERRS = (struct.error, OSError, AttributeError, ValueError, TypeError)
#| FLUSH_MAX_S = 2.0
#| GAP_S = 0.4
#| SWEEP_S = 0.5
#| # The game clock going back this far is a new match.
#| NEW_MATCH_BACK_S = 60.0
#| # A new match's utterances wait this long for its replay file, then go.
#| HOLD_MAX_S = 180.0
#| # Recent frames remembered for dedup (a few seconds of a full server).
#| SEEN_MAX = 20000
#| class LiveRing:
#|     def __init__(self, cap: int = 512):
#|         self._items, self._cap, self._lock = [], cap, threading.Lock()
#|     def add(self, u):
#|         with self._lock:
#|             self._items.append(u)
#|             self._items = self._items[-self._cap:]
#|     def since(self, start):
#|         with self._lock:
#|             return [u for u in self._items if u["startElapsed"] > start]
#| class MatchFollower:
#|     """Which match's voice-track an utterance goes to, on a live server."""
#|     FRESH_S = 60.0
#|     def __init__(self, replay_dir: str, now=time.time):
#|         self.dir, self._now = replay_dir, now
#|         self._files = {}                      # epoch -> match key
#|         self._tracks = {}                     # match key -> VoiceTrack
#|     def _active(self):
#|         best, best_t = None, -1.0
#|         for path in glob.glob(os.path.join(self.dir, "*.sqrx")) + glob.glob(os.path.join(self.dir, "*.ndjson")):
#|             try:
#|                 t = os.path.getmtime(path)
#|             except OSError:
#|                 continue
#|             if t > best_t:
#|                 best, best_t = path, t
#|         if best is None or self._now() - best_t > self.FRESH_S:
#|             return None
#|         return os.path.basename(best).rsplit(".", 1)[0]
#|     def track_for(self, epoch: int):
#|         if epoch not in self._files:
#|             key = self._active()
#|             if key is None or key in self._files.values():
#|                 return None
#|             self._files[epoch] = key
#|         key = self._files[epoch]
#|         if key not in self._tracks:
#|             self._tracks[key] = VoiceTrack(self.dir, key)
#|         return self._tracks[key]
#|     def tracks(self):
#|         return list(self._tracks.values())
#| class _FixedTrack:
#|     """One known match (the squad2 launcher passes its key)."""
#|     def __init__(self, track: VoiceTrack):
#|         self._t = track
#|     def track_for(self, epoch: int):
#|         return self._t
#|     def tracks(self):
#|         return [self._t]
#| STALL_S = 3.0          # GameState.ElapsedTime moves every second during a match
#| REFIND_MIN_S = 15.0
#| REFIND_MAX_S = 30.0
#| class VoiceEnricher:
#|     def __init__(self, reader, channel_names, track, live: LiveRing, start_poll: bool = True):
#|         self.reader, self.names, self.live = reader, channel_names, live
#|         self.tracks = track if hasattr(track, "track_for") else _FixedTrack(track)
#|         self.smap = SenderMap()
#|         self.smap.refresh(reader)
#|         # GameState.ElapsedTime is whole seconds (int32); a frame's time is
#|         self._elapsed = 0.0
#|         self._t0 = time.monotonic()
#|         self._next_find = 0.0                 # clock watchdog (clock_tick)
#|         self._find_every = REFIND_MIN_S
#|         self._epoch = 0
#|         self._bufs = {}                       # (sender, channel) -> frames
#|         self._held = []                       # (utterance, ogg bytes, held at)
#|         # Squad repeats a frame in later packets and sends each packet to
#|         self._seen = collections.OrderedDict()
#|         self._lock = threading.Lock()
#|         # Set by stop(): the background loops end. A capture that moves on to
#|         self._stop = threading.Event()
#|         # Counters for the periodic status line (ops: is anything arriving?).
#|         self.stats = {"frames": 0, "emitted": 0, "dropped": 0, "errors": 0}
#|         if start_poll:
#|             threading.Thread(target=self._poll_elapsed, daemon=True).start()
#|             threading.Thread(target=self._sweep_loop, daemon=True).start()
#|     # The background loops must never die silently: a dead clock froze every
#|     def _guard(self, what, exc):
#|         self.stats["errors"] += 1
#|         if self.stats["errors"] <= 5:
#|             print(f"# voice-enricher: {what}: {type(exc).__name__}: {exc}", flush=True)
#|     def _set_elapsed(self, e: float):
#|         if e < self._elapsed - NEW_MATCH_BACK_S:
#|             self._epoch += 1                  # the game clock restarted: a new match
#|         if e != self._elapsed:
#|             self._elapsed = e
#|             self._t0 = time.monotonic()
#|     def _now(self) -> float:
#|         return self._elapsed + min(max(time.monotonic() - self._t0, 0.0), 0.999)
#|     def stop(self):
#|         """End the background loops (the clock poll and the idle sweep)."""
#|         self._stop.set()
#|     def _poll_elapsed(self):
#|         while not self._stop.is_set():
#|             try:
#|                 self.clock_tick(time.monotonic())
#|             except Exception as exc:          # noqa: BLE001 -- see _guard
#|                 self._guard("clock", exc)
#|             self._stop.wait(0.1)              # the fraction is off by at most this
#|     def clock_tick(self, now: float):
#|         """Read the game clock once; when it has not moved for STALL_S,"""
#|         self._set_elapsed(float(self.reader.read_game_info().get("elapsedTime") or 0.0))
#|         if now - self._t0 < STALL_S or now < self._next_find:
#|             return
#|         # As the agent's loop does at a map change: the cached PersistentLevel
#|         self.reader.persistent_level_ptr = None
#|         for cache in ("fname_cache", "class_cache"):
#|             c = getattr(self.reader, cache, None)
#|             if hasattr(c, "clear"):
#|                 c.clear()
#|         gs = self.reader._find_game_state_instance()
#|         old = getattr(self.reader, "game_state", None)
#|         if gs and gs != old:
#|             self.reader.game_state = gs
#|             self._find_every = REFIND_MIN_S
#|             print(f"# voice-enricher: game clock was stuck at {self._elapsed:.1f}; "
#|                   f"GameState re-found ({hex(old) if old else None} -> {hex(gs)})", flush=True)
#|         else:
#|             self._find_every = min(self._find_every * 2, REFIND_MAX_S)
#|         self._next_find = now + self._find_every
#|     def _sweep_loop(self):
#|         last_status = time.monotonic()
#|         while not self._stop.wait(SWEEP_S):
#|             try:
#|                 self.sweep()
#|             except Exception as exc:          # noqa: BLE001 -- see _guard
#|                 self._guard("sweep", exc)
#|             if time.monotonic() - last_status >= 30:
#|                 last_status = time.monotonic()
#|                 print("# voice-enricher: " + self.status(), flush=True)
#|     def status(self) -> str:
#|         active = getattr(self.tracks, "_active", lambda: None)()
#|         return (f"frames={self.stats['frames']} open={len(self._bufs)} emitted={self.stats['emitted']} "
#|                 f"held={len(self._held)} dropped={self.stats['dropped']} errors={self.stats['errors']} "
#|                 f"elapsed={self._elapsed:.1f} epoch={self._epoch} active={active}")
#|     def on_frame(self, raw: bytes):
#|         try:
#|             self.stats["frames"] += 1
#|             # The perf record comes padded past sizeof(frame_t): read its first 80.
#|             sender, seq, ch, _flag, length, _pad, data = _FRAME.unpack_from(raw)
#|             eos, name = self.smap.lookup(self.reader, sender)
#|             f = {"eosId": eos, "displayName": name,
#|                  "channel": self.names.get(ch), "seq": seq,
#|                  "elapsed": self._now(), "epoch": self._epoch, "frame": data[:length]}
#|             fkey = (sender, f["frame"])
#|             if fkey in self._seen:
#|                 return
#|             self._seen[fkey] = None
#|             if len(self._seen) > SEEN_MAX:
#|                 self._seen.popitem(last=False)
#|             key = (sender, ch)
#|             with self._lock:
#|                 buf = self._bufs.get(key)
#|                 if buf and (f["elapsed"] - buf[-1]["elapsed"] > GAP_S or f["epoch"] != buf[-1]["epoch"]):
#|                     self._flush_key(key)
#|                     buf = None
#|                 if buf is None:
#|                     buf = self._bufs[key] = []
#|                 buf.append(f)
#|                 if f["elapsed"] - buf[0]["elapsed"] >= FLUSH_MAX_S:
#|                     self._flush_key(key)
#|         except _READ_ERRS as exc:
#|             self._guard("frame", exc)
#|     def _flush_key(self, key):
#|         frames = self._bufs.pop(key, None)
#|         if not frames:
#|             return
#|         epoch = frames[0]["epoch"]
#|         for u in group_utterances(frames, GAP_S):
#|             u["displayName"] = frames[0]["displayName"]
#|             self._emit(u, ogg_opus_mux(u["frames"]), epoch, time.monotonic())
#|     def _emit(self, u, ogg, epoch, held_at):
#|         track = self.tracks.track_for(epoch)
#|         if track is None:
#|             if time.monotonic() - held_at < HOLD_MAX_S:
#|                 self._held.append((u, ogg, epoch, held_at))
#|             else:
#|                 self.stats["dropped"] += 1
#|             return
#|         name = track.next_clip_name()
#|         track.write_clip(name, ogg)
#|         track.append(u, name, save=False)
#|         self.stats["emitted"] += 1
#|         self.live.add({k: u[k] for k in
#|                        ("eosId", "displayName", "channel", "startElapsed", "endElapsed")}
#|                       | {"clip": name})
#|     def sweep(self, save: bool = True):
#|         """Flush speakers who went quiet, retry held utterances, save the"""
#|         now = self._now()
#|         with self._lock:
#|             for key in [k for k, b in self._bufs.items()
#|                         if self._epoch != b[-1]["epoch"] or now - b[-1]["elapsed"] > GAP_S]:
#|                 self._flush_key(key)
#|             held, self._held = self._held, []
#|             for u, ogg, epoch, held_at in held:
#|                 self._emit(u, ogg, epoch, held_at)
#|             if save:
#|                 for t in self.tracks.tracks():
#|                     if getattr(t, "dirty", False):
#|                         t.save()
#|     def flush_all(self, save: bool = True):
#|         with self._lock:
#|             for key in list(self._bufs):
#|                 self._flush_key(key)
#|             if save:
#|                 for t in self.tracks.tracks():
#|                     if getattr(t, "dirty", False):
#|                         t.save()
#| def serve(reader, channel_names, replay_dir, match_key, sock_path, live: LiveRing):
#|     """Bind the tap socket and enrich frames forever. Creates the socket, so"""
#|     track = MatchFollower(replay_dir) if match_key is None else VoiceTrack(replay_dir, match_key)
#|     enr = VoiceEnricher(reader, channel_names, track, live)
#|     try:
#|         os.unlink(sock_path)
#|     except OSError:
#|         pass
#|     os.makedirs(os.path.dirname(sock_path), exist_ok=True)
#|     rx = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
#|     rx.bind(sock_path)
#|     while True:
#|         try:
#|             raw, _ = rx.recvfrom(128)
#|             enr.on_frame(raw)
#|         except _READ_ERRS:
#|             continue
#| class _UploadTrack:
#|     """One match's track that routes utterances to the uploader instead of"""
#|     def __init__(self, match_id, uploader):
#|         self._mid = match_id
#|         self._up = uploader
#|         self._n = 0
#|         self._pending = {}        # clip name -> ogg bytes, until append pairs it
#|         self.dirty = False
#|     def next_clip_name(self):
#|         name = "u%06d" % self._n
#|         self._n += 1
#|         return name
#|     def write_clip(self, name, ogg):
#|         self._pending[name] = ogg
#|     def append(self, u, name, save=False):
#|         ogg = self._pending.pop(name, b"")
#|         meta = {"eosId": u["eosId"], "displayName": u.get("displayName"),
#|                 "channel": u["channel"], "startElapsed": u["startElapsed"],
#|                 "endElapsed": u["endElapsed"],
#|                 "dur": round(u["endElapsed"] - u["startElapsed"], 3)}
#|         self._up.enqueue(self._mid, name, meta, ogg)
#|     def save(self):
#|         self.dirty = False
#| def _reader_match_id(reader):
#|     """Read ``gameInfo.matchId`` from the shared reader; ``None`` if unknown."""
#|     try:
#|         gi = reader.read_game_info() if reader is not None else {}
#|         return (gi.get("matchId") or "").strip() or None
#|     except _READ_ERRS:
#|         return None
#| class RemoteVoiceSink:
#|     """Track-provider for remote upload. One ``_UploadTrack`` per match id,"""
#|     def __init__(self, reader, uploader, *, match_id_of=None):
#|         self._reader = reader
#|         self._up = uploader
#|         self._match_id_of = match_id_of or _reader_match_id
#|         self._by_epoch = {}       # epoch -> _UploadTrack
#|     def track_for(self, epoch):
#|         t = self._by_epoch.get(epoch)
#|         if t is not None:
#|             return t
#|         mid = self._match_id_of(self._reader)
#|         if not mid:
#|             return None
#|         t = self._by_epoch[epoch] = _UploadTrack(mid, self._up)
#|         return t
#|     def tracks(self):
#|         return list(self._by_epoch.values())
#| def serve_upload(reader, channel_names, sock_path, uploader, live: LiveRing, stop=None):
#|     """Like :func:`serve`, but route utterances to the uploader (remote host)."""
#|     sink = RemoteVoiceSink(reader, uploader)
#|     enr = VoiceEnricher(reader, channel_names, sink, live)
#|     try:
#|         os.unlink(sock_path)
#|     except OSError:
#|         pass
#|     os.makedirs(os.path.dirname(sock_path), exist_ok=True)
#|     rx = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
#|     rx.bind(sock_path)
#|     if stop is not None:
#|         rx.settimeout(0.5)                    # wake up to look at ``stop``
#|     try:
#|         while stop is None or not stop.is_set():
#|             try:
#|                 raw, _ = rx.recvfrom(128)
#|                 enr.on_frame(raw)
#|             except _READ_ERRS:                # includes the socket timeout
#|                 continue
#|     finally:
#|         enr.stop()
#|         try:
#|             enr.flush_all()
#|         except Exception:                     # noqa: BLE001 -- the old reader may be dead
#|             pass
#|         rx.close()
#| ===== module: agent.voice_run =====
#| """voice-enricher host runner -- attaches a reader to the game PID and serves"""
#| import hashlib
#| import json
#| import logging
#| import os
#| import sys
#| logger = logging.getLogger("voice-run")
#| def parse_voice_run_args(argv):
#|     """Route voice_run's argv into a mode dict. Pure (no side effects) so the"""
#|     if argv and argv[0] == "--remote":
#|         # --remote <base_url> <agent_id> <secret_hex> <pid> <sock_path>
#|         if len(argv) < 6:
#|             raise SystemExit(__doc__)
#|         _, base_url, agent_id, secret_hex, pid, sock = argv[:6]
#|         return {"mode": "remote", "base_url": base_url, "agent_id": agent_id,
#|                 "secret_hex": secret_hex, "pid": int(pid), "sock_path": sock}
#|     if len(argv) == 4:
#|         pid, replay_dir, match_key, sock = argv
#|         return {"mode": "local", "pid": int(pid), "replay_dir": replay_dir,
#|                 "match_key": match_key, "sock_path": sock}
#|     if len(argv) == 3:
#|         pid, replay_dir, sock = argv
#|         return {"mode": "local", "pid": int(pid), "replay_dir": replay_dir,
#|                 "match_key": None, "sock_path": sock}
#|     raise SystemExit(__doc__)
#| def build_tap_argv(python_bin, tap_path, *, pid, binary, sock,
#|                    func_vaddr, offsets, owner):
#|     """Exact argv (under sudo) to launch the tap with payload-provided"""
#|     return [
#|         "sudo", python_bin, tap_path,
#|         str(pid), binary, sock, str(owner),
#|         "--func-vaddr", hex(func_vaddr),
#|         "--offsets", json.dumps(offsets, separators=(",", ":")),
#|     ]
#| def _squad_build_sha(binary_path):
#|     """sha256 of the game binary -- the build id the voice payload is scoped to"""
#|     h = hashlib.sha256()
#|     with open(binary_path, "rb") as fh:
#|         for chunk in iter(lambda: fh.read(1 << 20), b""):
#|             h.update(chunk)
#|     return h.hexdigest()
#| def resolve_probe_address(probe, binary, build_sha):
#|     """Where to attach the uprobe in ``binary``, or ``None`` for "do not"."""
#|     resolver = getattr(probe, "resolve_func_vaddr", None)
#|     try:
#|         if resolver is not None:
#|             return resolver(binary)
#|         if getattr(probe, "SQUAD_BUILD", None) == build_sha:
#|             return probe.FUNC_VADDR
#|     except Exception:
#|         logger.exception("voice: probe address resolution failed")
#|     return None
#| def _extract_tap_from_bundle(bundle_path, dest_path):
#|     """Materialise the embedded ``agent.voice_tap`` source to ``dest_path``."""
#|     out, grabbing = [], False
#|     with open(bundle_path, encoding="utf-8", newline="") as fh:
#|         for raw in fh:
#|             if raw.startswith("#| ===== "):
#|                 grabbing = raw.rstrip("\n").rstrip(" =").endswith(": agent.voice_tap")
#|                 continue
#|             if grabbing and raw.startswith("#|"):
#|                 out.append(raw[3:] if raw.startswith("#| ")
#|                            else ("\n" if raw.strip() == "#|" else raw[2:]))
#|     if not out:
#|         raise FileNotFoundError("agent.voice_tap not embedded in the bundle")
#|     with open(dest_path, "w", encoding="utf-8") as fh:
#|         fh.write("".join(out))
#|     os.chmod(dest_path, 0o700)
#| def _tap_script_path():
#|     """Path to voice_tap.py: the on-disk file in a source checkout; the fixed"""
#|     here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_tap.py")
#|     if os.path.isfile(here):
#|         return here
#|     import agent._runtime as _rt
#|     bundle, dest = _rt.bundle_path(), _rt.voice_tap_path()
#|     if bundle is None or dest is None:
#|         raise FileNotFoundError("voice_tap.py not found (neither checkout nor bundle)")
#|     _extract_tap_from_bundle(str(bundle), str(dest))
#|     return str(dest)
#| # Seconds. Module level so the tests can shrink them.
#| WATCH_S = 2.0               # how often a running capture looks at the game and the tap
#| SETUP_RETRY_S = 300.0       # the payload / probe setup failed (network, central): try again
#| NEW_PID_POLL_S = 5.0        # waiting for the game to come back
#| NEW_GAME_GRACE_S = 30.0     # a new game process is still loading its first map
#| TAP_RESPAWN_S = 10.0        # the tap died while the game is up: start it again
#| TAP_FAST_FAIL_S = 30.0      # a tap that lives shorter than this counts as failing
#| TAP_MAX_FAST_FAILS = 3      # ... and after this many in a row it is left alone
#| def _proc_start(pid):
#|     """The kernel's start time of ``pid`` (an opaque token), or ``None`` when"""
#|     try:
#|         with open(f"/proc/{pid}/stat", "rb") as fh:
#|             raw = fh.read()
#|         fields = raw[raw.rindex(b")") + 2:].split()
#|         if fields[0] == b"Z":
#|             return None
#|         return fields[19]
#|     except (OSError, ValueError, IndexError):
#|         return None
#| def _spawn_tap(argv):
#|     import subprocess
#|     try:
#|         return subprocess.Popen(argv)
#|     except OSError as exc:
#|         logger.warning("voice tap spawn failed: %s", exc)
#|         return None
#| def run_remote_capture(*, base_url, agent_id, secret, pid, sock_path, pid_source=None):
#|     """Load the signed voice payload, spawn the tap with its constants, and"""
#|     import threading
#|     import time
#|     from sq_reader import SquadMemoryReader
#|     from sq_session import build_reader
#|     from agent.voice_enricher import LiveRing, serve_upload
#|     from agent.payload_client import PayloadFetchError, load_payload
#|     from agent.updater import AGENT_VERSION
#|     from agent.voice_uploader import VoiceUploader
#|     uploader = []                   # created once, with the first successful setup
#|     shas = {}                       # (pid, start) -> build sha: the binary is read once
#|     def capture_game(game_pid):
#|         """Capture from one game process. Returns why it ended: ``gone`` (the"""
#|         binary = f"/proc/{game_pid}/exe"
#|         started = _proc_start(game_pid)
#|         if started is None:
#|             return "gone"
#|         try:
#|             # The payload is bound to the build it was made for unless it says it
#|             if (game_pid, started) not in shas:
#|                 shas[(game_pid, started)] = _squad_build_sha(binary)
#|             build_sha = shas[(game_pid, started)]
#|             load_payload(base_url=base_url, agent_id=agent_id, agent_secret=secret,
#|                          kind="voice", agent_version=AGENT_VERSION, have_version=0,
#|                          squad_build=build_sha)
#|             import voice_probe  # installed by the payload loader
#|             tap = _tap_script_path()
#|         except (PayloadFetchError, OSError, ImportError) as exc:
#|             logger.warning("voice capture not started: %s", exc)
#|             return "setup"
#|         func_vaddr = resolve_probe_address(voice_probe, binary, build_sha)
#|         if func_vaddr is None:
#|             logger.warning("voice capture not started: this game build (%s) does not "
#|                            "match the probe; the function was not found exactly once",
#|                            build_sha[:8])
#|             return "unsupported"
#|         logger.info("voice: probe address %#x for game build %s", func_vaddr, build_sha[:8])
#|         try:
#|             reader = build_reader(game_pid)
#|         except Exception as exc:    # noqa: BLE001 -- a game still loading its first map
#|             logger.warning("voice capture not started: cannot read the game yet: %s", exc)
#|             return "setup"
#|         if not uploader:
#|             up = VoiceUploader(base_url, agent_id, secret)
#|             up.start()
#|             uploader.append(up)
#|         argv = build_tap_argv("/usr/bin/python3", tap, pid=game_pid, binary=binary,
#|                               sock=sock_path, func_vaddr=func_vaddr,
#|                               offsets=voice_probe.PACKET_OFFSETS, owner=os.getpid())
#|         stop = threading.Event()
#|         def _serve():
#|             try:
#|                 serve_upload(reader, SquadMemoryReader.VOICE_CHANNEL_NAMES, sock_path,
#|                              uploader[0], LiveRing(), stop)
#|             except Exception:       # noqa: BLE001
#|                 logger.exception("voice: the enricher crashed")
#|         server = threading.Thread(target=_serve, name="squad-voice-serve", daemon=True)
#|         server.start()
#|         time.sleep(1.0)             # let serve_upload bind the socket first
#|         print(f"# voice(remote): pid={game_pid} -> {base_url}/ingest/voice", flush=True)
#|         proc, spawned_at, fast_fails = None, 0.0, 0
#|         outcome = "gone"
#|         try:
#|             while _proc_start(game_pid) == started:
#|                 if not server.is_alive():
#|                     outcome = "setup"           # nothing receives the tap's frames
#|                     break
#|                 if proc is None or proc.poll() is not None:
#|                     if proc is not None:
#|                         # poll() has reaped it. Died soon after it started = failing.
#|                         fast_fails = (fast_fails + 1
#|                                       if time.monotonic() - spawned_at < TAP_FAST_FAIL_S else 0)
#|                         logger.warning("voice tap exited (rc=%s) while the game is up",
#|                                        proc.returncode)
#|                     if fast_fails >= TAP_MAX_FAST_FAILS:
#|                         logger.error("voice tap keeps failing; leaving it until the "
#|                                      "game restarts")
#|                         proc = None
#|                         while _proc_start(game_pid) == started:
#|                             time.sleep(WATCH_S)
#|                         break
#|                     if proc is not None:
#|                         time.sleep(TAP_RESPAWN_S)
#|                     proc = _spawn_tap(argv)
#|                     spawned_at = time.monotonic()
#|                     if proc is None:
#|                         fast_fails += 1
#|                 time.sleep(WATCH_S)
#|         finally:
#|             stop.set()
#|             if proc is not None and proc.poll() is None:
#|                 try:
#|                     proc.terminate()
#|                 except OSError:
#|                     pass
#|             server.join(5.0)
#|         if outcome == "gone":
#|             logger.info("voice: game process %d is gone", game_pid)
#|         return outcome
#|     while True:
#|         try:
#|             outcome = capture_game(pid)
#|         except Exception:           # noqa: BLE001 -- voice must never take the agent down
#|             logger.exception("voice: capture crashed (non-fatal)")
#|             outcome = "setup"
#|         if pid_source is None:
#|             return
#|         if outcome == "setup":
#|             if _proc_start(pid) is not None:
#|                 time.sleep(SETUP_RETRY_S)           # same process, try the setup again
#|                 continue
#|         # The process is gone (or cannot be probed): wait for the next one.
#|         while True:
#|             try:
#|                 nxt = pid_source()
#|             except Exception:       # noqa: BLE001
#|                 nxt = None
#|             if nxt and nxt != pid and _proc_start(nxt) is not None:
#|                 break
#|             time.sleep(NEW_PID_POLL_S)
#|         logger.info("voice: the game restarted (pid %d -> %d); capturing again", pid, nxt)
#|         time.sleep(NEW_GAME_GRACE_S)
#|         pid = nxt
#| def main():
#|     a = parse_voice_run_args(sys.argv[1:])
#|     if a["mode"] == "remote":
#|         run_remote_capture(base_url=a["base_url"], agent_id=a["agent_id"],
#|                            secret=bytes.fromhex(a["secret_hex"]),
#|                            pid=a["pid"], sock_path=a["sock_path"])
#|         return
#|     from sq_reader import SquadMemoryReader
#|     from sq_session import build_reader
#|     from agent.voice_enricher import LiveRing, serve
#|     reader = build_reader(a["pid"])
#|     print(f"# voice-enricher: pid={a['pid']} match={a['match_key'] or 'follow'}",
#|           flush=True)
#|     serve(reader, SquadMemoryReader.VOICE_CHANNEL_NAMES,
#|           a["replay_dir"], a["match_key"], a["sock_path"], LiveRing())
#| if __name__ == "__main__":
#|     main()
#| ===== module: agent.voice_tap =====
#| """voice-tap -- production-safe eBPF voice capture (the privileged half of the"""
#| import argparse
#| import ctypes
#| import json
#| import os
#| import signal
#| import socket
#| import sys
#| import threading
#| import time
#| MAX_FRAME = 64              # observed frame len 50; clamp (matches the wire struct)
#| MAX_ENTRIES = 16            # observed Num <= ~8; bound the loop for the verifier
#| def build_bpf_source(offsets, *, max_frame=MAX_FRAME, max_entries=MAX_ENTRIES):
#|     """Render the BPF C with the packet field offsets injected. No struct"""
#|     tmpl = r"""
#| #include <uapi/linux/ptrace.h>
#|
#| struct frame_t {
#|     u64 sender;
#|     u32 seq;
#|     u8  ch;
#|     u8  flag;
#|     u8  len;
#|     u8  _pad;
#|     u8  data[%(MAX_FRAME)d];
#| };
#| BPF_PERF_OUTPUT(frames);
#| // dedup: hash(sender,seq,firstbytes) -> 1. LRU, not BPF_HASH: a plain hash
#| // stops inserting at its 10,240 default and every copy then reached
#| // userspace -- minutes of speech on a full server.
#| BPF_TABLE("lru_hash", u64, u8, seen, 65536);
#| BPF_PERCPU_ARRAY(scratch, struct frame_t, 1);
#|
#| int on_serialize(struct pt_regs *ctx) {
#|     u64 self = PT_REGS_PARM1(ctx);
#|     u32 num = 0;
#|     bpf_probe_read_user(&num, sizeof(num), (void *)(self + %(OFF_NUM)d));
#|     if (num == 0) return 0;
#|     if (num > %(MAX_ENTRIES)d) num = %(MAX_ENTRIES)d;
#|
#|     u64 entries = 0;
#|     bpf_probe_read_user(&entries, sizeof(entries), (void *)(self + %(OFF_ENTRIES)d));
#|     if (entries == 0) return 0;
#|
#|     int zero = 0;
#|     struct frame_t *f = scratch.lookup(&zero);
#|     if (!f) return 0;
#|     bpf_probe_read_user(&f->sender, sizeof(f->sender), (void *)(self + %(OFF_SENDER)d));
#|     bpf_probe_read_user(&f->seq,    sizeof(f->seq),    (void *)(self + %(OFF_SEQ)d));
#|     bpf_probe_read_user(&f->ch,     sizeof(f->ch),     (void *)(self + %(OFF_CH)d));
#|     bpf_probe_read_user(&f->flag,   sizeof(f->flag),   (void *)(self + %(OFF_FLAG)d));
#|     u8 len = 0;
#|     bpf_probe_read_user(&len, sizeof(len), (void *)(self + %(OFF_LEN)d));
#|     if (len == 0 || len > %(MAX_FRAME)d) return 0;
#|     f->len = len;
#|
#|     #pragma unroll
#|     for (int i = 0; i < %(MAX_ENTRIES)d; i++) {
#|         if (i >= num) break;
#|         u64 ptrA = 0, ptrB = 0;
#|         bpf_probe_read_user(&ptrA, sizeof(ptrA), (void *)(entries + i * 0x10));
#|         if (!ptrA) continue;
#|         bpf_probe_read_user(&ptrB, sizeof(ptrB), (void *)ptrA);
#|         if (!ptrB) continue;
#|         __builtin_memset(f->data, 0, sizeof(f->data));
#|         bpf_probe_read_user(f->data, %(MAX_FRAME)d, (void *)ptrB);
#|
#|         // A frame is its speaker and its bytes: Squad repeats it in later
#|         // packets (another i) and sends each packet to every listener
#|         // (another seq) -- neither belongs in the key (live squad1 had
#|         // ~10 copies per frame with them in).
#|         // Only the frame's own `len` bytes: the 64-byte read runs past it
#|         // into memory that differs between copies of the same frame.
#|         u64 k = f->sender ^ ((u64)f->len << 56);
#|         #pragma unroll
#|         for (int w = 0; w < %(MAX_FRAME)d / 8; w++) {
#|             int left = (int)len - w * 8;
#|             if (left <= 0) break;
#|             u64 word = 0;
#|             __builtin_memcpy(&word, &f->data[w * 8], 8);
#|             if (left < 8) word &= (1ULL << (left * 8)) - 1;
#|             k = (k ^ word) * 1099511628211ULL;   /* FNV-1a 64-bit prime */
#|         }
#|         u8 one = 1;
#|         if (seen.lookup(&k)) continue;
#|         seen.update(&k, &one);
#|
#|         frames.perf_submit(ctx, f, sizeof(*f));
#|     }
#|     return 0;
#| }
#| """
#|     return tmpl % {
#|         "MAX_FRAME": max_frame, "MAX_ENTRIES": max_entries,
#|         "OFF_NUM": offsets["num"], "OFF_ENTRIES": offsets["entries"],
#|         "OFF_SENDER": offsets["sender"], "OFF_SEQ": offsets["seq"],
#|         "OFF_CH": offsets["ch"], "OFF_FLAG": offsets["flag"],
#|         "OFF_LEN": offsets["len"],
#|     }
#| def main():
#|     ap = argparse.ArgumentParser()
#|     ap.add_argument("pid", type=int)
#|     ap.add_argument("binary")
#|     ap.add_argument("sock_path")
#|     # Optional: the launcher's PID. Started under sudo from a script, the tap
#|     ap.add_argument("owner", nargs="?", type=int, default=None)
#|     ap.add_argument("--func-vaddr", required=True,
#|                     help="FSquadVoicePacket::Serialize vaddr (from the voice payload)")
#|     ap.add_argument("--offsets", required=True,
#|                     help="JSON dict of packet offsets (from the voice payload)")
#|     a = ap.parse_args()
#|     func_vaddr = int(a.func_vaddr, 0)
#|     offsets = json.loads(a.offsets)
#|     pid, binary, sock_path, owner = a.pid, a.binary, a.sock_path, a.owner
#|     from bcc import BPF
#|     # A background job of a non-interactive shell starts with SIGINT ignored.
#|     signal.signal(signal.SIGINT, signal.default_int_handler)
#|     signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
#|     def watchdog():
#|         while True:
#|             time.sleep(2)
#|             for p in (owner, pid):
#|                 if p is not None and not os.path.exists(f"/proc/{p}"):
#|                     os._exit(0)          # the kernel drops the uprobe with the process
#|     threading.Thread(target=watchdog, daemon=True).start()
#|     tx = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
#|     b = BPF(text=build_bpf_source(offsets))
#|     b.attach_uprobe(name=binary, addr=func_vaddr, fn_name="on_serialize", pid=pid)
#|     def handle(cpu, data, size):
#|         try:
#|             tx.sendto(ctypes.string_at(data, size), sock_path)   # enricher may be down
#|         except OSError:
#|             pass
#|     b["frames"].open_perf_buffer(handle, page_cnt=256)
#|     print("# voice-tap attached pid=%d -> %s (process NOT stopped)" % (pid, sock_path))
#|     while True:
#|         b.perf_buffer_poll(timeout=500)
#| if __name__ == "__main__":
#|     main()
#| ===== module: agent.voice_uploader =====
#| """Ship finalized utterances from a remote host to central's /ingest/voice."""
#| import base64
#| import collections
#| import logging
#| import threading
#| import time
#| import urllib.error
#| import urllib.request
#| from ingest.protocol import encode_voice_envelope
#| logger = logging.getLogger("voice-uploader")
#| # One post carries at most this much audio (the base64 text, which is what
#| MAX_BATCH_BYTES = 1_500_000
#| MAX_BATCH_ITEMS = 150
#| MIN_BATCH_BYTES = 60_000          # a 413 may halve the limit, never below this
#| # Voice that could not be delivered for this long is dropped: the match it
#| MAX_AGE_SECONDS = 900.0
#| MAX_QUEUE_BYTES = 48 * 1024 * 1024
#| MAX_PAUSE_SECONDS = 60.0
#| def _http_post(url: str, body: bytes) -> int:
#|     # User-Agent matters: Cloudflare's bot protection 403s requests without a
#|     req = urllib.request.Request(
#|         url, data=body,
#|         headers={"Content-Type": "application/json",
#|                  "User-Agent": "SquadReplay/1.0"})
#|     try:
#|         with urllib.request.urlopen(req, timeout=10) as r:
#|             return r.status
#|     except urllib.error.HTTPError as e:
#|         # An answer is not an outage: hand the status to flush_once, which
#|         return e.code
#| class VoiceUploader:
#|     def __init__(self, base_url, agent_id, agent_secret, *,
#|                  batch_interval=2.5, max_queue=2000, poster=None,
#|                  max_batch_bytes=MAX_BATCH_BYTES, max_batch_items=MAX_BATCH_ITEMS,
#|                  max_age=MAX_AGE_SECONDS, max_queue_bytes=MAX_QUEUE_BYTES, clock=time.monotonic):
#|         self.url = base_url.rstrip("/") + "/ingest/voice"
#|         self.agent_id = agent_id
#|         self.secret = agent_secret
#|         self.batch_interval = batch_interval
#|         self.max_queue = max_queue
#|         self.max_batch_bytes = max_batch_bytes
#|         self.max_batch_items = max_batch_items
#|         self.max_age = max_age
#|         self.max_queue_bytes = max_queue_bytes
#|         self._clock = clock
#|         self._poster = poster or _http_post
#|         self._q = collections.deque()
#|         self._bytes = 0
#|         self._lock = threading.Lock()
#|         self._seq = 0
#|         self._stop = threading.Event()
#|         self._thread = None
#|         self._fail_streak = 0
#|         self._stats = {"queued": 0, "sent": 0, "dropped": 0, "retries": 0}
#|         self._last_posted_clips = []     # test seam
#|     @staticmethod
#|     def _size(item):
#|         return len(item["ogg_b64"]) + 200
#|     def _drop_oldest(self):
#|         old = self._q.popleft()
#|         self._bytes -= self._size(old)
#|         self._stats["dropped"] += 1
#|     def enqueue(self, match_id, clip_name, utterance, ogg):
#|         item = {"matchId": match_id, "clip": clip_name,
#|                 "u": utterance, "ogg_b64": base64.b64encode(ogg).decode(),
#|                 "t": self._clock()}
#|         with self._lock:
#|             while self._q and (len(self._q) >= self.max_queue
#|                                or self._bytes + self._size(item) > self.max_queue_bytes):
#|                 self._drop_oldest()
#|             self._q.append(item)
#|             self._bytes += self._size(item)
#|             self._stats["queued"] = len(self._q)
#|     def _drain_grouped(self):
#|         now = self._clock()
#|         with self._lock:
#|             items = list(self._q)
#|             self._q.clear()
#|             self._bytes = 0
#|             self._stats["queued"] = 0
#|         fresh = [it for it in items if now - it["t"] <= self.max_age]
#|         self._stats["dropped"] += len(items) - len(fresh)
#|         groups = collections.OrderedDict()
#|         for it in fresh:
#|             groups.setdefault(it["matchId"], []).append(it)
#|         return groups
#|     def _requeue_front(self, items):
#|         with self._lock:
#|             self._q.extendleft(reversed(items))
#|             self._bytes += sum(self._size(it) for it in items)
#|             while self._q and (len(self._q) > self.max_queue or self._bytes > self.max_queue_bytes):
#|                 old = self._q.pop()          # keep the OLDEST of a retry backlog's front, drop the newest
#|                 self._bytes -= self._size(old)
#|                 self._stats["dropped"] += 1
#|             self._stats["queued"] = len(self._q)
#|     def _chunks(self, items):
#|         """The items of one match in posts of bounded size, order kept."""
#|         chunk, size = [], 0
#|         for it in items:
#|             sz = len(it["ogg_b64"])
#|             if chunk and (len(chunk) >= self.max_batch_items or size + sz > self.max_batch_bytes):
#|                 yield chunk
#|                 chunk, size = [], 0
#|             chunk.append(it)
#|             size += sz
#|         if chunk:
#|             yield chunk
#|     def _post(self, match_id, items):
#|         batch = {"matchId": match_id, "utterances": [
#|             dict(it["u"], clip=it["clip"], opus_b64=it["ogg_b64"])
#|             for it in items
#|         ]}
#|         self._seq += 1
#|         body = encode_voice_envelope(
#|             agent_id=self.agent_id, seq=self._seq,
#|             agent_secret=self.secret, batch=batch,
#|         )
#|         return self._poster(self.url, body)
#|     def flush_once(self):
#|         groups = self._drain_grouped()
#|         self._last_posted_clips = []
#|         pending = [(m, c) for m, items in groups.items() for c in self._chunks(items)]
#|         leftover = []
#|         for n, (match_id, items) in enumerate(pending):
#|             try:
#|                 status = self._post(match_id, items)
#|             except (OSError, ValueError) as e:
#|                 logger.info("voice post error: %s", e)
#|                 status = None
#|             if status is not None and 200 <= status < 300:
#|                 self._stats["sent"] += len(items)
#|                 self._last_posted_clips += [it["clip"] for it in items]
#|             elif status == 403:
#|                 # Not cleared: dropping is correct, retrying never helps.
#|                 self._stats["dropped"] += len(items)
#|             elif status == 413 and len(items) == 1:
#|                 # One clip alone is over central's cap: it can never go.
#|                 logger.info("voice clip %s is too large for central; dropped", items[0]["clip"])
#|                 self._stats["dropped"] += 1
#|             else:
#|                 if status == 413:
#|                     # Smaller posts from now on.
#|                     self.max_batch_bytes = max(MIN_BATCH_BYTES, self.max_batch_bytes // 2)
#|                     self.max_batch_items = max(1, self.max_batch_items // 2)
#|                 if status is not None:
#|                     logger.info("voice post refused: HTTP %s", status)
#|                 self._stats["retries"] += 1
#|                 # This post and everything behind it wait, in their order;
#|                 leftover = [it for _m, chunk in pending[n:] for it in chunk]
#|                 break
#|         if leftover:
#|             self._requeue_front(leftover)
#|         self._fail_streak = self._fail_streak + 1 if leftover else 0
#|     def stats(self):
#|         return dict(self._stats)
#|     def _pause(self):
#|         """Seconds to wait before the next flush: the interval, doubled for"""
#|         return min(MAX_PAUSE_SECONDS, self.batch_interval * (2 ** min(self._fail_streak, 5)))
#|     def _loop(self):
#|         while not self._stop.wait(self._pause()):
#|             try:
#|                 self.flush_once()
#|             except Exception:
#|                 logger.exception("voice flush loop error")   # never die
#|     def start(self):
#|         self._thread = threading.Thread(target=self._loop, daemon=True)
#|         self._thread.start()
#|     def stop(self):
#|         self._stop.set()
#|         if self._thread:
#|             self._thread.join(timeout=2)
#| ===== package: ingest =====
#| """ingest/__init__.py — Ingest subsystem."""
#| from __future__ import annotations
#| __all__ = ["crypto", "protocol", "store", "registry"]
#| ===== module: ingest.crypto =====
#| """ingest/crypto.py — Authenticated encryption helpers for agent → central-server ingest."""
#| from __future__ import annotations
#| import os
#| from dataclasses import dataclass
#| from functools import lru_cache
#| from cryptography.hazmat.primitives import hashes
#| from cryptography.hazmat.primitives.ciphers.aead import AESGCM
#| from cryptography.hazmat.primitives.kdf.hkdf import HKDF
#| # Key-derivation context. Changing this value invalidates every in-flight
#| HKDF_INFO = b"squad-ingest-v1"
#| # AES-GCM canonical nonce size. 12 bytes is the AES-GCM recommendation;
#| NONCE_SIZE = 12
#| class CryptoError(Exception):
#|     """Raised when decryption or authentication fails. The message is"""
#| @dataclass(frozen=True)
#| class EncryptedEnvelope:
#|     """Output of :func:`encrypt_snapshot` — plain bytes ready for transport."""
#|     nonce: bytes
#|     ciphertext: bytes
#| @lru_cache(maxsize=64)
#| def _derive_key_cached(secret_bytes: bytes, info: bytes) -> bytes:
#|     """Internal cached HKDF expansion. Keyed on (secret_bytes, info)"""
#|     hkdf = HKDF(
#|         algorithm=hashes.SHA256(),
#|         length=32,
#|         salt=b"",
#|         info=info,
#|     )
#|     return hkdf.derive(secret_bytes)
#| def derive_key(agent_secret: bytes, *, info: bytes = HKDF_INFO) -> bytes:
#|     """Derive the AES-256 session key from a long-lived agent secret."""
#|     if not isinstance(agent_secret, (bytes, bytearray)):
#|         raise TypeError("agent_secret must be bytes")
#|     if len(agent_secret) < 16:
#|         raise ValueError("agent_secret must be at least 16 bytes")
#|     return _derive_key_cached(bytes(agent_secret), info)
#| def build_aad(version: int, agent_id: str, seq: int, ts: int) -> bytes:
#|     """Construct the AAD bound to every ciphertext."""
#|     if "|" in agent_id:
#|         raise ValueError("agent_id must not contain '|'")
#|     return f"{version}|{agent_id}|{seq}|{ts}".encode("ascii")
#| def encrypt_snapshot(
#|     agent_secret: bytes,
#|     plaintext: bytes,
#|     *,
#|     version: int,
#|     agent_id: str,
#|     seq: int,
#|     ts: int,
#|     nonce: bytes | None = None,
#| ) -> EncryptedEnvelope:
#|     """Encrypt ``plaintext`` (raw snapshot bytes) for a single agent → server"""
#|     key = derive_key(agent_secret)
#|     aad = build_aad(version, agent_id, seq, ts)
#|     if nonce is None:
#|         nonce = os.urandom(NONCE_SIZE)
#|     elif len(nonce) != NONCE_SIZE:
#|         raise ValueError(f"nonce must be exactly {NONCE_SIZE} bytes")
#|     ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
#|     return EncryptedEnvelope(nonce=nonce, ciphertext=ciphertext)
#| VOICE_INFO = b"squad-voice-v1"
#| def encrypt_voice(
#|     agent_secret: bytes,
#|     plaintext: bytes,
#|     *,
#|     version: int,
#|     agent_id: str,
#|     seq: int,
#|     ts: int,
#|     nonce: bytes | None = None,
#| ) -> EncryptedEnvelope:
#|     """Encrypt a voice-batch plaintext. A separate HKDF info from the"""
#|     key = derive_key(agent_secret, info=VOICE_INFO)
#|     aad = build_aad(version, agent_id, seq, ts)
#|     if nonce is None:
#|         nonce = os.urandom(NONCE_SIZE)
#|     elif len(nonce) != NONCE_SIZE:
#|         raise ValueError(f"nonce must be exactly {NONCE_SIZE} bytes")
#|     ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
#|     return EncryptedEnvelope(nonce=nonce, ciphertext=ciphertext)
#| ===== module: ingest.offsets =====
#| """ingest/offsets.py — central → agent."""
#| from __future__ import annotations
#| import logging
#| from cryptography.hazmat.primitives.ciphers.aead import AESGCM
#| from .crypto import NONCE_SIZE, CryptoError, EncryptedEnvelope, derive_key
#| logger = logging.getLogger("squad_map_server.ingest.offsets")
#| RESP_AAD_TAG = b"resp"  # prefix distinguishes responses from ingest
#| def _build_response_aad(version: int, agent_id: str, seq: int, ts: int) -> bytes:
#|     """Construct the AAD bound to an offset response ciphertext."""
#|     if "|" in agent_id:
#|         raise ValueError("agent_id must not contain '|'")
#|     label = RESP_AAD_TAG.decode("ascii")
#|     return f"{label}|{version}|{agent_id}|{seq}|{ts}".encode("ascii")
#| def open_response_envelope(
#|     agent_secret: bytes,
#|     env: EncryptedEnvelope,
#|     *,
#|     agent_id: str,
#|     seq: int,
#|     ts: int,
#|     version: int = 1,
#| ) -> bytes:
#|     """Agent-side counterpart to :func:`build_response_envelope`."""
#|     if len(env.nonce) != NONCE_SIZE:
#|         raise CryptoError("bad nonce length")
#|     key = derive_key(agent_secret)
#|     aad = _build_response_aad(version, agent_id, seq, ts)
#|     try:
#|         return AESGCM(key).decrypt(env.nonce, env.ciphertext, aad)
#|     except Exception as e:  # InvalidTag etc. — never leak the cause.
#|         raise CryptoError("decrypt failed") from e
#| ===== module: ingest.protocol =====
#| """ingest/protocol.py — Wire-format for agent → central ingest."""
#| from __future__ import annotations
#| import base64
#| import gzip
#| import json
#| import time
#| from .crypto import encrypt_snapshot, encrypt_voice
#| PROTOCOL_VERSION = 1
#| # Maximum allowed clock skew between agent and central server, seconds.
#| MAX_TS_SKEW_SECONDS = 120
#| # Hard ceiling on compressed payload size. Memory snapshots are ~150 KB
#| MAX_CIPHERTEXT_BYTES = 5 * 1024 * 1024
#| def _b64url_encode(data: bytes) -> str:
#|     return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
#| def encode_envelope(
#|     *,
#|     agent_id: str,
#|     seq: int,
#|     agent_secret: bytes,
#|     snapshot_json: bytes,
#|     ts: int | None = None,
#|     nonce: bytes | None = None,
#|     version: int = PROTOCOL_VERSION,
#| ) -> bytes:
#|     """Encrypt + frame a single snapshot for transport. Returns the raw"""
#|     if ts is None:
#|         ts = int(time.time())
#|     plaintext = gzip.compress(snapshot_json, compresslevel=6)
#|     env = encrypt_snapshot(
#|         agent_secret,
#|         plaintext,
#|         version=version,
#|         agent_id=agent_id,
#|         seq=seq,
#|         ts=ts,
#|         nonce=nonce,
#|     )
#|     body = {
#|         "v": version,
#|         "agent_id": agent_id,
#|         "seq": seq,
#|         "ts": ts,
#|         "nonce": _b64url_encode(env.nonce),
#|         "ciphertext": _b64url_encode(env.ciphertext),
#|     }
#|     return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
#| def encode_voice_envelope(
#|     *,
#|     agent_id: str,
#|     seq: int,
#|     agent_secret: bytes,
#|     batch: dict,
#|     ts: int | None = None,
#|     nonce: bytes | None = None,
#|     version: int = PROTOCOL_VERSION,
#| ) -> bytes:
#|     """Encrypt + frame one voice batch for transport. Same wire body shape"""
#|     if ts is None:
#|         ts = int(time.time())
#|     plaintext = gzip.compress(
#|         json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
#|         compresslevel=6,
#|     )
#|     env = encrypt_voice(
#|         agent_secret, plaintext,
#|         version=version, agent_id=agent_id, seq=seq, ts=ts, nonce=nonce,
#|     )
#|     body = {
#|         "v": version, "agent_id": agent_id, "seq": seq, "ts": ts,
#|         "nonce": _b64url_encode(env.nonce),
#|         "ciphertext": _b64url_encode(env.ciphertext),
#|     }
#|     return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
#| ===== module: ingest.variants =====
#| """ingest/variants.py -- the agent variants and the update channels they use."""
#| from __future__ import annotations
#| #: Every variant the project ships, in the order they are listed everywhere.
#| VARIANTS = ("read", "read-write", "read-voice", "read-write-voice")
#| #: The compiled-binary channel (unchanged since before variants existed).
#| BINARY_PLATFORM = "linux"
#| _BUNDLE_PREFIX = "linux-py-"
#| def bundle_platform(variant: str) -> str:
#|     """``read`` -> ``linux-py-read``. Raises for a name that is not a variant."""
#|     if variant not in VARIANTS:
#|         raise ValueError(f"not an agent variant: {variant!r}")
#|     return _BUNDLE_PREFIX + variant
#| #: Every platform token central will route to a manifest.
#| PLATFORM_TAGS = (BINARY_PLATFORM,) + tuple(bundle_platform(v) for v in VARIANTS)
#| def variant_of_platform(tag: str) -> str | None:
#|     """``linux-py-read-write`` -> ``read-write``; ``linux`` / junk -> None."""
#|     if isinstance(tag, str) and tag.startswith(_BUNDLE_PREFIX):
#|         v = tag[len(_BUNDLE_PREFIX):]
#|         if v in VARIANTS:
#|             return v
#|     return None
#| def is_platform_tag(tag: object) -> bool:
#|     """Whether central may use ``tag`` to pick a manifest file. An allowlist,"""
#|     return isinstance(tag, str) and tag in PLATFORM_TAGS
#| def artifact_name(variant: str, version: str) -> str:
#|     """The published file for a variant at a version."""
#|     if variant not in VARIANTS:
#|         raise ValueError(f"not an agent variant: {variant!r}")
#|     return f"squadreplay-agent-{variant}-{version}.py"
#| __all__ = ["BINARY_PLATFORM", "PLATFORM_TAGS", "VARIANTS", "artifact_name",
#|            "bundle_platform", "is_platform_tag", "variant_of_platform"]
#| ===== module: live_data_mmap =====
#| """live_data_mmap.py — Shared-memory live data channel."""
#| from __future__ import annotations
#| import mmap
#| import os
#| import struct
#| import time
#| from pathlib import Path
#| MAGIC = b"SQLD"            # "Squad Live Data"
#| VERSION = 1
#| HEADER_SIZE = 64           # magic(4) + version(4) + seq(8) + length(8) + 40 reserved
#| _HEADER_FMT = "<4sIQQ40x"  # little-endian: bytes, uint32, uint64, uint64, 40 pad
#| assert struct.calcsize(_HEADER_FMT) == HEADER_SIZE
#| DEFAULT_CAPACITY = 8 * 1024 * 1024  # 8 MiB body (header excluded)
#| _MAX_READER_RETRIES = 8             # seqlock retry budget
#| _BUSY_SPIN_SLEEP = 0.001            # 1 ms between retries
#| class BodyTooLargeError(Exception):
#|     """Raised when the snapshot doesn't fit in the allocated mmap."""
#| class CorruptMmapError(Exception):
#|     """Raised when the header doesn't look like ours (wrong magic/version)."""
#| def _default_path(json_path: Path) -> Path:
#|     """Sidecar path: ``squad_live_data.json`` -> ``squad_live_data.mmap``."""
#|     return json_path.with_suffix(".mmap")
#| class LiveDataWriter:
#|     """Single-writer side. Owns the file and grows it to full capacity."""
#|     def __init__(self, path: Path, capacity: int = DEFAULT_CAPACITY) -> None:
#|         self.path = Path(path)
#|         self.capacity = capacity
#|         self._total = HEADER_SIZE + capacity
#|         # Ensure the backing file exists and is at least total size. We fill
#|         fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
#|         try:
#|             st = os.fstat(fd)
#|             if st.st_size < self._total:
#|                 os.ftruncate(fd, self._total)
#|             self._mm = mmap.mmap(fd, self._total, access=mmap.ACCESS_WRITE)
#|         finally:
#|             os.close(fd)
#|         self._write_initial_header_if_needed()
#|     def _write_initial_header_if_needed(self) -> None:
#|         """If the magic is missing or wrong, initialize the header."""
#|         self._mm.seek(0)
#|         magic = self._mm.read(4)
#|         if magic != MAGIC:
#|             self._mm.seek(0)
#|             self._mm.write(struct.pack(_HEADER_FMT, MAGIC, VERSION, 0, 0))
#|             self._mm.flush()
#|     def _read_seq(self) -> int:
#|         self._mm.seek(8)  # skip magic(4) + version(4)
#|         return struct.unpack("<Q", self._mm[8:16])[0]
#|     def _write_seq(self, seq: int) -> None:
#|         self._mm[8:16] = struct.pack("<Q", seq)
#|     def _write_length(self, length: int) -> None:
#|         self._mm[16:24] = struct.pack("<Q", length)
#|     def write(self, data: bytes) -> None:
#|         """Publish a new snapshot. Raises BodyTooLargeError on overflow."""
#|         if len(data) > self.capacity:
#|             raise BodyTooLargeError(
#|                 f"snapshot {len(data)} B > capacity {self.capacity} B"
#|             )
#|         seq = self._read_seq()
#|         # Step 1: seq -> odd (write in progress)
#|         self._write_seq(seq + 1)
#|         # Step 2: length + body
#|         self._write_length(len(data))
#|         self._mm[HEADER_SIZE:HEADER_SIZE + len(data)] = data
#|         # Step 3: seq -> even (publish)
#|         self._write_seq(seq + 2)
#|     def close(self) -> None:
#|         try:
#|             self._mm.flush()
#|         finally:
#|             self._mm.close()
#|     def __enter__(self) -> "LiveDataWriter":
#|         return self
#|     def __exit__(self, *_: object) -> None:
#|         self.close()
#| class LiveDataReader:
#|     """Read-only side. Safe for concurrent readers via seqlock."""
#|     def __init__(self, path: Path) -> None:
#|         self.path = Path(path)
#|         fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
#|         try:
#|             st = os.fstat(fd)
#|             size = st.st_size
#|             if size < HEADER_SIZE:
#|                 raise CorruptMmapError(f"file too small: {size} < {HEADER_SIZE}")
#|             self._mm = mmap.mmap(fd, size, access=mmap.ACCESS_READ)
#|         finally:
#|             os.close(fd)
#|         # Remember the inode we actually mapped so a later on-disk swap
#|         self._ino = st.st_ino
#|         self._dev = st.st_dev
#|         magic = bytes(self._mm[0:4])
#|         version = struct.unpack("<I", self._mm[4:8])[0]
#|         if magic != MAGIC:
#|             raise CorruptMmapError(f"bad magic: {magic!r}")
#|         if version != VERSION:
#|             raise CorruptMmapError(f"unsupported version: {version}")
#|     def is_replaced(self) -> bool:
#|         """True if ``self.path`` now points at a different inode than the"""
#|         try:
#|             st = os.stat(self.path)
#|         except OSError:
#|             return True
#|         return st.st_ino != self._ino or st.st_dev != self._dev
#|     def read(self) -> bytes | None:
#|         """Return a consistent snapshot, or None if no snapshot has been"""
#|         for _ in range(_MAX_READER_RETRIES):
#|             s1 = struct.unpack("<Q", self._mm[8:16])[0]
#|             if s1 == 0:
#|                 return None
#|             if s1 & 1:
#|                 time.sleep(_BUSY_SPIN_SLEEP)
#|                 continue  # writer mid-write
#|             length = struct.unpack("<Q", self._mm[16:24])[0]
#|             if length == 0 or HEADER_SIZE + length > len(self._mm):
#|                 return None
#|             body = bytes(self._mm[HEADER_SIZE:HEADER_SIZE + length])
#|             s2 = struct.unpack("<Q", self._mm[8:16])[0]
#|             if s1 == s2:
#|                 return body
#|             # Torn read — writer raced us. Retry.
#|             time.sleep(_BUSY_SPIN_SLEEP)
#|         return None  # writer thrashed; let caller fall back to file
#|     def close(self) -> None:
#|         self._mm.close()
#|     def __enter__(self) -> "LiveDataReader":
#|         return self
#|     def __exit__(self, *_: object) -> None:
#|         self.close()
#| ===== module: proc_utils =====
#| """proc_utils.py — Process utilities for single-instance enforcement."""
#| from __future__ import annotations
#| import logging
#| import os
#| import signal
#| from agent._platform import (
#|     IS_LINUX,
#|     find_pid as _plat_find_pid,
#|     list_processes_by_name as _plat_list_processes,
#| )
#| logger = logging.getLogger(__name__)
#| def kill_previous_instances(script_marker: str, timeout: float = 5.0) -> int:
#|     """Kill any other Python/Nuitka processes whose command line contains"""
#|     if not IS_LINUX:
#|         return 0
#|     current_pid = os.getpid()
#|     # Image names to sweep. The installed interpreter could be
#|     image_candidates = ("python", "python3", "python3.10",
#|                         "python3.11", "python3.12", "python3.13",
#|                         "SquadReplay")
#|     seen_pids: set[int] = set()
#|     victims: list[int] = []
#|     for image in image_candidates:
#|         try:
#|             rows = _plat_list_processes(image)
#|         except NotImplementedError:
#|             return 0
#|         for pid, cmd in rows:
#|             if pid == current_pid or pid in seen_pids:
#|                 continue
#|             seen_pids.add(pid)
#|             if script_marker in cmd:
#|                 victims.append(pid)
#|     if not victims:
#|         return 0
#|     killed = 0
#|     for pid in victims:
#|         if _terminate_pid(pid, timeout):
#|             logger.warning(
#|                 "Killed orphan %s (pid=%s) from previous run",
#|                 script_marker, pid,
#|             )
#|             killed += 1
#|     return killed
#| def _terminate_pid(pid: int, timeout: float) -> bool:
#|     """Kill a PID via SIGTERM → short wait → SIGKILL. Returns True on"""
#|     if not IS_LINUX:
#|         return False
#|     try:
#|         os.kill(pid, signal.SIGTERM)
#|     except (ProcessLookupError, PermissionError) as exc:
#|         logger.warning("Failed to TERM orphan pid=%s: %s", pid, exc)
#|         return False
#|     import time
#|     for _ in range(10):
#|         time.sleep(0.1)
#|         try:
#|             os.kill(pid, 0)
#|         except ProcessLookupError:
#|             return True
#|     try:
#|         os.kill(pid, signal.SIGKILL)
#|     except (ProcessLookupError, PermissionError):
#|         pass
#|     return True
#| def find_process_pid(
#|     image_name: str,
#|     executable_path: str | None = None,
#|     match_cmdline: str | None = None,
#|     timeout: float = 5.0,   # kept for call-site compatibility
#| ) -> int | None:
#|     """Find the PID of a running process by image name (e.g."""
#|     try:
#|         return _plat_find_pid(image_name, executable_path, match_cmdline)
#|     except NotImplementedError:
#|         return None
#|     except OSError as exc:
#|         logger.warning("find_process_pid failed: %s", exc)
#|         return None
#| ===== module: squad_memory_reader =====
#| """squad_memory_reader.py -- the SquadReplay agent's entry point (the loader)."""
#| import os
#| import sys
#| import json
#| import time
#| import argparse
#| import logging
#| import gc
#| import signal
#| import logging.handlers
#| from pathlib import Path
#| import math
#| def _auto_load_env_files() -> None:
#|     """Populate ``os.environ`` from ``.env.agent`` and ``.env.map_server``"""
#|     # .env.map_server first so .env.agent's more-specific values take
#|     for path_str in ('.env.map_server', '.env.agent'):
#|         try:
#|             with open(Path(path_str), 'r', encoding='utf-8') as f:
#|                 for raw in f:
#|                     line = raw.strip()
#|                     if not line or line.startswith('#') or '=' not in line:
#|                         continue
#|                     key, _, val = line.partition('=')
#|                     key = key.strip()
#|                     val = val.strip()
#|                     if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
#|                         val = val[1:-1]
#|                     if key and not os.environ.get(key):
#|                         os.environ[key] = val
#|         except (FileNotFoundError, OSError, ValueError):
#|             pass
#| _auto_load_env_files()
#| from proc_utils import kill_previous_instances, find_process_pid
#| from live_data_mmap import LiveDataWriter, BodyTooLargeError, DEFAULT_CAPACITY
#| # The Squad-specific reader. In a checkout it sits next to this file; a
#| try:
#|     import sq_reader as _sq_reader
#|     from sq_reader import SquadMemoryReader
#| except ModuleNotFoundError as _exc:
#|     if _exc.name != "sq_reader":
#|         raise
#|     _sq_reader = None
#|     SquadMemoryReader = None  # type: ignore[assignment,misc]
#| # The Squad tick (the ``session`` payload, layered on ``read``). Absent in the
#| try:
#|     import sq_session as _sq_session
#| except ModuleNotFoundError as _exc:
#|     if _exc.name not in ("sq_session", "sq_reader"):
#|         raise
#|     _sq_session = None
#| # Optional — only used when --push is enabled.
#| try:
#|     from ingest import protocol as ingest_protocol
#| except ImportError:  # pragma: no cover — ingest package always present locally
#|     ingest_protocol = None  # type: ignore[assignment]
#| import binascii
#| sys.stdout.reconfigure(encoding='utf-8', errors='replace')
#| logger = logging.getLogger("SquadReplay")
#| # ---------------------------------------------------------------------------
#| # Rules: keep keys exact (case-sensitive class names), values opaque.
#| _PUBLIC_EXC_NAMES = {
#|     # Memory access path — pymem / native backend.
#|     "MemoryReadError":          "SquadReplayCheckError",
#|     "MemoryWriteError":         "SquadReplayCheckError",
#|     "ProcessNotFound":          "SquadReplayCheckError",
#|     "CouldNotOpenProcess":      "SquadReplayCheckError",
#|     # Wire protocol + crypto.
#|     "CryptoError":              "SquadReplayAuthError",
#|     "InvalidTag":               "SquadReplayAuthError",
#|     "InvalidKey":               "SquadReplayAuthError",
#|     "ProtocolError":            "SquadReplayWireError",
#|     "StaleSnapshotError":       "SquadReplayStateError",
#|     # Capacity / format.
#|     "BodyTooLargeError":        "SquadReplayCapacityError",
#|     "ReplayFormatError":        "SquadReplayArchiveError",
#|     # Stdlib leaks (struct parsing, IO, decoding).
#|     "error":                    "SquadReplayDecodeError",      # struct.error
#|     "OSError":                  "SquadReplayIOError",
#|     "PermissionError":          "SquadReplayIOError",
#|     "FileNotFoundError":        "SquadReplayIOError",
#|     "TimeoutError":             "SquadReplayIOError",
#|     "ConnectionError":          "SquadReplayIOError",
#|     "URLError":                 "SquadReplayIOError",
#|     "HTTPError":                "SquadReplayIOError",
#|     # Programmer-error-ish (still surface but opaque).
#|     "AttributeError":           "SquadReplayStateError",
#|     "ValueError":               "SquadReplayInputError",
#|     "TypeError":                "SquadReplayInputError",
#|     "KeyError":                 "SquadReplayStateError",
#|     "IndexError":               "SquadReplayStateError",
#|     "ZeroDivisionError":        "SquadReplayStateError",
#| }
#| def _public_exc_name(exc_type) -> str:
#|     """Map an internal exception class to its operator-facing name."""
#|     try:
#|         return _PUBLIC_EXC_NAMES.get(exc_type.__name__, "SquadReplayError")
#|     except AttributeError:
#|         return "SquadReplayError"
#| def _redacted_excepthook(exc_type, exc, tb):
#|     """Replace ``sys.excepthook`` so uncaught exceptions emit a single"""
#|     # KeyboardInterrupt + SystemExit: respect them with no log spam.
#|     if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
#|         sys.__excepthook__(exc_type, exc, tb)
#|         return
#|     public = _public_exc_name(exc_type)
#|     try:
#|         msg = str(exc) if exc is not None else "<no message>"
#|     except (AttributeError, TypeError, ValueError):
#|         msg = "<unprintable>"
#|     # One-liner, no frames, no module qualifiers.
#|     try:
#|         logger.error("service error: %s: %s", public, msg)
#|     except (OSError, ValueError):
#|         # logger might be misconfigured — fall back to raw stderr write.
#|         try:
#|             sys.stderr.write(f"SquadReplay service error: {public}: {msg}\n")
#|         except OSError:
#|             pass
#| # Install the hook + zero traceback frames at module load time so any
#| sys.excepthook = _redacted_excepthook
#| sys.tracebacklimit = 0
#| class IngestPusher:
#|     """Encrypts and POSTs snapshots to a central ingest endpoint."""
#|     _CONTENT_TYPE = "application/json"
#|     _TIMEOUT_SEC = 10.0
#|     def __init__(
#|         self,
#|         *,
#|         url: str,
#|         agent_id: str,
#|         secret_hex: str,
#|         seq_state_path: Path,
#|     ) -> None:
#|         if ingest_protocol is None:
#|             raise RuntimeError(
#|                 "ingest package unavailable — cannot run in --push mode"
#|             )
#|         # Normalize: the server exposes /ingest/snapshot; accept either
#|         url = url.rstrip("/")
#|         if not url.endswith("/ingest/snapshot"):
#|             url = url + "/ingest/snapshot"
#|         self._url = url
#|         self._agent_id = agent_id
#|         try:
#|             self._secret = binascii.unhexlify(secret_hex.strip())
#|         except (binascii.Error, ValueError) as e:
#|             raise ValueError(f"--secret-hex is not valid hex: {e}") from e
#|         if len(self._secret) < 16:
#|             raise ValueError("--secret-hex must encode at least 16 bytes")
#|         self._seq_path = seq_state_path
#|         self._seq = self._load_seq()
#|         self._last_error_repr: str | None = None
#|         # Threaded in from SquadMemoryReader._offset_health by the caller
#|         self._offset_health: dict = {'healed': 0, 'warnings': 0}
#|         # Persistent HTTPS connection pool. Without this, every push went
#|         import urllib3 as _urllib3
#|         from urllib.parse import urlparse as _urlparse
#|         _parsed = _urlparse(self._url)
#|         self._http_pool = _urllib3.PoolManager(
#|             num_pools=4,
#|             maxsize=2,
#|             timeout=_urllib3.Timeout(connect=5.0, read=self._TIMEOUT_SEC),
#|             retries=_urllib3.Retry(total=0, connect=0, read=0),
#|             cert_reqs="CERT_REQUIRED" if _parsed.scheme == "https" else "CERT_NONE",
#|         )
#|     @property
#|     def secret(self) -> bytes:
#|         """Read-only access to the decoded shared secret. Used by the"""
#|         return self._secret
#|     def _load_seq(self) -> int:
#|         try:
#|             raw = self._seq_path.read_text(encoding="utf-8").strip()
#|             value = int(raw)
#|             if value < 0:
#|                 raise ValueError("negative seq")
#|             return value
#|         except (FileNotFoundError, ValueError, OSError):
#|             return 0
#|     def _save_seq(self) -> None:
#|         try:
#|             self._seq_path.parent.mkdir(parents=True, exist_ok=True)
#|             self._seq_path.write_text(str(self._seq), encoding="utf-8")
#|         except OSError as e:
#|             # Non-fatal — on next restart we'd resend from a lower seq
#|             logger.warning("cannot persist push seq to %s: %s", self._seq_path, e)
#|     def push(self, snapshot_json_bytes: bytes) -> bool:
#|         """Encrypt and POST one snapshot. Returns True on 2xx, False on"""
#|         assert ingest_protocol is not None
#|         # Tentative seq — only committed to disk after the server accepts
#|         seq_to_send = self._seq + 1
#|         try:
#|             envelope = ingest_protocol.encode_envelope(
#|                 agent_id=self._agent_id,
#|                 seq=seq_to_send,
#|                 agent_secret=self._secret,
#|                 snapshot_json=snapshot_json_bytes,
#|             )
#|         except Exception as e:  # pragma: no cover — encryption shouldn't fail
#|             logger.exception("push encode failed: %s", e)
#|             return False
#|         # Build a User-Agent string that the central can parse for
#|         try:
#|             from agent.updater import AGENT_VERSION as _agent_version
#|         except ImportError:
#|             _agent_version = "0"
#|         try:
#|             from agent.updater import _platform_tag as _plat_tag
#|             _plat = _plat_tag()
#|         except (ImportError, AttributeError):
#|             _plat = "linux"
#|         try:
#|             from agent.capabilities import header_value as _caps_header
#|             _caps = _caps_header()
#|         except ImportError:
#|             _caps = "read"
#|         # Use the persistent connection pool. PoolManager keeps the
#|         try:
#|             resp = self._http_pool.request(
#|                 "POST",
#|                 self._url,
#|                 body=envelope,
#|                 headers={
#|                     "Content-Type": self._CONTENT_TYPE,
#|                     # User-Agent matters with Cloudflare in front —
#|                     "User-Agent": f"SquadReplay/{_agent_version} ({_plat})",
#|                     # F6: restart telemetry for the central manager
#|                     "X-Agent-Restarts": os.environ.get('SQUAD_AGENT_RESTARTS', '0'),
#|                     "X-Agent-Consec": os.environ.get('SQUAD_AGENT_CONSEC_CRASHES', '0'),
#|                     "X-Offset-Health": (
#|                         f"healed={self._offset_health['healed']},"
#|                         f"warnings={self._offset_health['warnings']}"
#|                     ),
#|                     # Which variant this is (read / read,write) -- the
#|                     "X-Agent-Capabilities": _caps,
#|                 },
#|                 preload_content=False,
#|             )
#|         except Exception as e:  # noqa: BLE001 — transport-level error
#|             self._log_error(str(e))
#|             return False
#|         try:
#|             status = resp.status
#|             if 200 <= status < 300:
#|                 self._seq = seq_to_send
#|                 self._save_seq()
#|                 if self._last_error_repr is not None:
#|                     logger.info("push: recovered, server accepted seq %d",
#|                                 self._seq)
#|                     self._last_error_repr = None
#|                 return True
#|             if status == 409:
#|                 # 409 Conflict — central thinks our seq is stale. Rebase
#|                 rebased_to = None
#|                 try:
#|                     body = resp.read()
#|                     if body:
#|                         import json as _json
#|                         payload = _json.loads(body.decode("utf-8",
#|                                                           errors="replace"))
#|                         last_seq = int(payload.get("lastSeq", 0))
#|                         if last_seq > self._seq:
#|                             self._seq = last_seq + 1
#|                             rebased_to = self._seq
#|                 except (ValueError, KeyError, TypeError, OSError):
#|                     pass
#|                 if rebased_to is not None:
#|                     logger.warning(
#|                         "push: server rejected as stale (409); rebased "
#|                         "local seq to %d (was behind central)",
#|                         rebased_to,
#|                     )
#|                 else:
#|                     logger.warning(
#|                         "push: server rejected seq %d as stale (409). "
#|                         "Continuing with next seq. If this repeats every "
#|                         "tick, central is on a pre-rebase build — delete "
#|                         "%s and restart to force resync.",
#|                         seq_to_send, self._seq_path,
#|                     )
#|                 self._save_seq()
#|                 return False
#|             self._log_error(f"HTTP {status}")
#|             return False
#|         finally:
#|             # Always release the connection back to the pool — otherwise
#|             try:
#|                 resp.drain_conn()
#|             except Exception:  # noqa: BLE001
#|                 pass
#|             try:
#|                 resp.release_conn()
#|             except Exception:  # noqa: BLE001
#|                 pass
#|     def _log_error(self, reason: str) -> None:
#|         # Rate-limit identical errors so a disconnected central server
#|         if self._last_error_repr == reason:
#|             return
#|         self._last_error_repr = reason
#|         logger.warning("push: %s (url=%s, seq=%d)", reason, self._url, self._seq)
#| def _restart_agent() -> None:
#|     """Manager asked for a restart: arrange the relaunch, then leave through the normal Ctrl-C path"""
#|     from agent import _runtime, updater
#|     path = _runtime.bundle_path()
#|     if path is None:
#|         logger.warning("control: restart requested but this is not a one-file agent; ignoring")
#|         return
#|     logger.info("control: restart requested by the manager")
#|     updater.relaunch_later(path, delay=5)
#|     os.kill(os.getpid(), signal.SIGINT)
#| def _configure_logging(level_name: str, log_file: str | None) -> None:
#|     level = getattr(logging, level_name.upper(), logging.INFO)
#|     root = logging.getLogger()
#|     # Reset handlers (important when this process is relaunched repeatedly)
#|     for h in list(root.handlers):
#|         root.removeHandler(h)
#|     fmt = logging.Formatter(
#|         fmt="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
#|         datefmt="%Y-%m-%d %H:%M:%S",
#|     )
#|     stream = logging.StreamHandler(sys.stdout)
#|     stream.setFormatter(fmt)
#|     stream.setLevel(level)
#|     root.addHandler(stream)
#|     if log_file:
#|         try:
#|             p = Path(log_file)
#|             p.parent.mkdir(parents=True, exist_ok=True)
#|             # Rotate at local midnight, keep 7 daily backups (FIFO — the
#|             fh = logging.handlers.TimedRotatingFileHandler(
#|                 p, when="midnight", backupCount=7, encoding="utf-8"
#|             )
#|             fh.setFormatter(fmt)
#|             fh.setLevel(level)
#|             root.addHandler(fh)
#|         except (OSError, PermissionError):
#|             # Can't create the log file (permission denied, read-only fs,
#|             pass
#|     root.setLevel(level)
#|     # Silence noisy third-party DEBUG logs unless explicitly debugging
#|     if level > logging.DEBUG:
#|         logging.getLogger("pymem").setLevel(logging.WARNING)
#| # ----------------------------------------------------------------------
#| def _agent_dir() -> Path:
#|     """Directory next to the running binary / source."""
#|     onefile_dir = os.environ.get("NUITKA_ONEFILE_DIRECTORY")
#|     if onefile_dir:
#|         p = Path(onefile_dir)
#|         if p.is_dir():
#|             return p
#|     return Path(__file__).resolve().parent
#| DEFAULT_CONFIG_PATH = _agent_dir() / "squad_replay_config.json"
#| # Older deploys shipped with this name; auto-fallback at load time keeps
#| LEGACY_CONFIG_PATH = _agent_dir() / "squad_reader_config.json"
#| def sanitize_nan(obj):
#|     """Replace NaN/Inf floats with None recursively."""
#|     if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
#|         return None
#|     if isinstance(obj, dict):
#|         return {k: sanitize_nan(v) for k, v in obj.items()}
#|     if isinstance(obj, list):
#|         return [sanitize_nan(v) for v in obj]
#|     return obj
#| def _load_mod_reader_configs() -> dict:
#|     """Scan mods/ directory and merge classes.json overrides from enabled mods."""
#|     mods_dir = Path(__file__).parent / 'mods'
#|     result: dict[str, list[str]] = {
#|         'admin_cam_patterns': [],
#|         'soldier_class_patterns': [],
#|     }
#|     if not mods_dir.is_dir():
#|         return result
#|     for mod_dir in sorted(mods_dir.iterdir()):
#|         if not mod_dir.is_dir():
#|             continue
#|         try:
#|             meta = json.loads((mod_dir / 'meta.json').read_text(encoding='utf-8'))
#|             if not meta.get('enabled', True):
#|                 continue
#|         except Exception:
#|             continue
#|         classes_cfg_path = mod_dir / 'classes.json'
#|         if not classes_cfg_path.exists():
#|             continue
#|         try:
#|             cfg = json.loads(classes_cfg_path.read_text(encoding='utf-8'))
#|             for key in result:
#|                 for p in cfg.get(key, []):
#|                     if isinstance(p, str) and p and p not in result[key]:
#|                         result[key].append(p)
#|         except Exception:
#|             continue
#|     return result
#| def _bind_reader_host() -> None:
#|     """Give the Squad reader the loader-side pieces it cannot find itself"""
#|     if _sq_reader is not None:
#|         _sq_reader.bind_host(load_mod_configs=_load_mod_reader_configs)
#|     if _sq_session is not None:
#|         _sq_session.bind_host(agent_dir=_agent_dir())
#| _bind_reader_host()
#| def _fetch_payload(kind: str, *, base_url: str, agent_id: str, agent_secret: bytes) -> None:
#|     """Fetch, verify and install signed payload ``kind``. Exits the way the"""
#|     try:
#|         from agent.payload_client import PayloadFetchError, load_payload
#|         from agent.updater import AGENT_VERSION
#|     except ImportError as exc:
#|         logger.error("payload client unavailable (%s); this file cannot load "
#|                      "the reader without it.", exc)
#|         sys.exit(2)
#|     try:
#|         load_payload(base_url=base_url, agent_id=agent_id,
#|                      agent_secret=agent_secret, kind=kind,
#|                      agent_version=AGENT_VERSION, have_version=0)
#|     except PayloadFetchError as exc:
#|         logger.error("could not load the %s code from central (%s). Check the "
#|                      "--push URL, agent id and secret, and that this agent is "
#|                      "up to date.", kind, exc)
#|         # The loader itself may be what central no longer supports; one
#|         try:
#|             from agent import updater as _updater
#|             if _updater.check_and_apply(base_url):
#|                 logger.info("updater: applied a newer agent while recovering "
#|                             "from a payload failure -- exiting for restart")
#|                 sys.exit(0)
#|         except ImportError:
#|             pass
#|         sys.exit(3)
#| def _ensure_squad_reader(*, base_url: str, agent_id: str,
#|                          agent_secret: bytes) -> None:
#|     """Make sure the Squad-specific code is loaded: the reader (``read``"""
#|     global _sq_reader, SquadMemoryReader, _sq_session
#|     import importlib
#|     if SquadMemoryReader is None:
#|         _fetch_payload("read", base_url=base_url, agent_id=agent_id,
#|                        agent_secret=agent_secret)
#|         _sq_reader = importlib.import_module("sq_reader")
#|         SquadMemoryReader = _sq_reader.SquadMemoryReader
#|         logger.info("Squad reader loaded from central")
#|     if _sq_session is None:
#|         try:
#|             _sq_session = importlib.import_module("sq_session")
#|         except ModuleNotFoundError as exc:
#|             if exc.name != "sq_session":
#|                 raise
#|             _fetch_payload("session", base_url=base_url, agent_id=agent_id,
#|                            agent_secret=agent_secret)
#|             _sq_session = importlib.import_module("sq_session")
#|             logger.info("Squad session loaded from central")
#|     _bind_reader_host()
#| def _load_mod_admin_cam_patterns() -> tuple[str, ...]:
#|     """Convenience wrapper — returns admin_cam_patterns tuple from all enabled mods."""
#|     return tuple(_load_mod_reader_configs()['admin_cam_patterns'])
#| def load_reader_config(path: Path | None) -> dict:
#|     """Load JSON config or return safe defaults. Never raises on missing file."""
#|     defaults = {
#|         "executable_path": None,
#|         "match_cmdline": None,
#|         "process_name": "SquadGameServer",
#|         "attach_retry_seconds": 5,
#|     }
#|     if path is not None:
#|         candidates = [path]
#|     else:
#|         candidates = [DEFAULT_CONFIG_PATH, LEGACY_CONFIG_PATH]
#|     cfg = None
#|     for p in candidates:
#|         try:
#|             with open(p, "r", encoding="utf-8") as fh:
#|                 cfg = json.load(fh)
#|             if p == LEGACY_CONFIG_PATH:
#|                 logger.info(
#|                     "Using legacy config %s — rename to %s at your "
#|                     "convenience; the legacy fallback will be removed in a "
#|                     "future release.",
#|                     LEGACY_CONFIG_PATH.name, DEFAULT_CONFIG_PATH.name,
#|                 )
#|             break
#|         except FileNotFoundError:
#|             continue
#|         except (OSError, json.JSONDecodeError) as e:
#|             logger.warning("Config load failed at %s (%s) — trying next", p, e)
#|             continue
#|     if cfg is None:
#|         logger.info("No service config found (looked at %s) — using defaults",
#|                     [str(c) for c in candidates])
#|         return defaults
#|     for k, v in defaults.items():
#|         cfg.setdefault(k, v)
#|     return cfg
#| def _is_pid_alive(pid: int) -> bool:
#|     """Return True if pid currently maps to a running process."""
#|     try:
#|         from agent._platform import is_pid_alive as _platform_alive
#|         return _platform_alive(pid)
#|     except ImportError:
#|         # Defensive fallback — should never trigger in a normal agent
#|         return bool(pid and pid > 0)
#| def _match_cmdline_for(config: dict) -> str | None:
#|     """The cmdline substring that selects the right SquadGameServer instance."""
#|     if config.get("match_cmdline"):
#|         return config["match_cmdline"]
#|     port = config.get("port")
#|     if port:
#|         return f"Port={int(port)}"
#|     return None
#| def discover_squad_pid(config: dict) -> int | None:
#|     """One-shot discovery. Returns PID or None."""
#|     return find_process_pid(
#|         image_name=config.get("process_name") or "SquadGameServer",
#|         executable_path=config.get("executable_path"),
#|         match_cmdline=_match_cmdline_for(config),
#|     )
#| def wait_for_squad_pid(config: dict, stop_check=None) -> int:
#|     """Block until a matching SquadGameServer process is running; return its PID."""
#|     interval = max(1, int(config.get("attach_retry_seconds", 5) or 5))
#|     want_path = config.get("executable_path")
#|     want_cmdline = _match_cmdline_for(config)
#|     image = config.get("process_name") or "SquadGameServer"
#|     attempts = 0
#|     first_log = True
#|     while True:
#|         if stop_check and stop_check():
#|             raise KeyboardInterrupt
#|         pid = discover_squad_pid(config)
#|         if pid:
#|             tag = ""
#|             if want_path:
#|                 tag += f" exe_path={want_path}"
#|             if want_cmdline:
#|                 tag += f" cmdline~={want_cmdline!r}"
#|             if not tag:
#|                 tag = " (name match)"
#|             logger.info("Service located%s", tag)
#|             return pid
#|         if first_log:
#|             logger.info(
#|                 "Waiting for %s (path=%s, cmdline=%s)… polling every %ds",
#|                 image, want_path or "<any>", want_cmdline or "<any>", interval,
#|             )
#|             first_log = False
#|         attempts += 1
#|         # Escalate log once per minute so operators see progress without spam.
#|         if attempts % max(1, 60 // interval) == 0:
#|             logger.info(
#|                 "Still waiting for %s (attempt %d)…", image, attempts,
#|             )
#|         time.sleep(interval)
#| def _extract_argv_value(flag: str) -> str | None:
#|     """Read ``--flag value`` or ``--flag=value`` from ``sys.argv`` without"""
#|     argv = sys.argv
#|     for i, a in enumerate(argv):
#|         if a == flag and i + 1 < len(argv):
#|             return argv[i + 1].strip() or None
#|         if a.startswith(flag + "="):
#|             return a.split("=", 1)[1].strip() or None
#|     return None
#| def _agent_can_write() -> bool:
#|     """Whether this build carries the write capability (queue priority)."""
#|     try:
#|         from agent.capabilities import WRITE, detect
#|     except ImportError:
#|         return True
#|     return WRITE in detect()
#| def _ensure_write_payload(*, base_url: str, agent_id: str,
#|                           agent_secret: bytes) -> bool:
#|     """Make ``queue_priority`` importable."""
#|     try:
#|         import queue_priority  # noqa: F401
#|         return True
#|     except ModuleNotFoundError as exc:
#|         if exc.name != "queue_priority":
#|             raise
#|     try:
#|         from agent.payload_client import PayloadFetchError, load_payload
#|         from agent.updater import AGENT_VERSION
#|     except ImportError as exc:
#|         logger.warning("queue priority unavailable: payload client missing (%s)", exc)
#|         return False
#|     try:
#|         load_payload(base_url=base_url, agent_id=agent_id, agent_secret=agent_secret,
#|                      kind="write", agent_version=AGENT_VERSION, have_version=0)
#|     except PayloadFetchError as exc:
#|         logger.warning("queue priority unavailable: could not load the write "
#|                        "payload from central (%s); continuing without it", exc)
#|         return False
#|     return True
#| def _agent_variant_name() -> str:
#|     try:
#|         from agent.capabilities import variant_name
#|     except ImportError:
#|         return "unknown"
#|     return variant_name()
#| class _LocalChannel:
#|     """The local half of publishing: the shared-memory sidecar the HTTP server"""
#|     def __init__(self, output, *, use_mmap=True, capacity=DEFAULT_CAPACITY):
#|         self.output = Path(output)
#|         self.capacity = capacity
#|         self._writer = None
#|         if use_mmap:
#|             try:
#|                 self._writer = LiveDataWriter(self.output.with_suffix('.mmap'),
#|                                               capacity=capacity)
#|                 logger.info("Data channel ready (capacity=%d bytes)", capacity)
#|             except OSError as e:
#|                 logger.warning("Data channel unavailable (%s) — using file fallback", e)
#|     def write(self, text: str) -> None:
#|         body = text.encode('utf-8')
#|         if self._writer is not None:
#|             try:
#|                 self._writer.write(body)
#|             except BodyTooLargeError:
#|                 # Auto-grow the mmap if the snapshot outgrew its capacity.
#|                 new_capacity = max(self.capacity * 2, len(body) + 1_000_000)
#|                 logger.info(
#|                     "mmap capacity %d too small for %d-byte snapshot — "
#|                     "recreating at %d bytes", self.capacity, len(body), new_capacity,
#|                 )
#|                 self._writer.close()
#|                 mmap_path = self.output.with_suffix('.mmap')
#|                 try:                        # wipe the stale file so the fresh header is unambiguous
#|                     mmap_path.unlink()
#|                 except OSError:
#|                     pass
#|                 self.capacity = new_capacity
#|                 self._writer = LiveDataWriter(mmap_path, capacity=new_capacity)
#|                 self._writer.write(body)
#|             except OSError as e:
#|                 logger.warning("Data channel write failed: %s — disabling", e)
#|                 try:
#|                     self._writer.close()
#|                 except OSError:
#|                     pass
#|                 self._writer = None
#|         with open(self.output, 'w', encoding='utf-8') as f:
#|             f.write(text)
#| # Consecutive full-snapshot push failures. Escalates log severity so a
#| _push_consec_fail = 0
#| def _publish(snapshot, *, pusher, mirror, channel, offset_health) -> bool:
#|     """The one place a tick's snapshot leaves the process: the local player-stats"""
#|     global _push_consec_fail
#|     # Sanitize once; every output reuses the same text.
#|     sanitized = sanitize_nan(snapshot)
#|     compact = json.dumps(sanitized, ensure_ascii=False)
#|     # Whatever the mirror does, the bytes pushed to central are already fixed.
#|     if mirror is not None:
#|         mirror.observe(sanitized)                        # never raises
#|     if channel is not None:
#|         try:
#|             channel.write(compact)
#|         except OSError as e:
#|             logger.warning("local snapshot write failed: %s", e)
#|     if pusher is None:
#|         return True
#|     pusher._offset_health = offset_health
#|     try:
#|         ok = pusher.push(compact.encode('utf-8'))
#|     except Exception:
#|         ok = False
#|         logger.exception("ingest push raised")           # never let a push bug stop memory reads
#|     if ok:
#|         if _push_consec_fail > 0:
#|             logger.info("ingest push recovered after %d consecutive failure(s)",
#|                         _push_consec_fail)
#|         _push_consec_fail = 0
#|     else:
#|         _push_consec_fail += 1
#|         # First, third, then every 10th failure logged loud: neither silence
#|         if _push_consec_fail in (1, 3) or _push_consec_fail % 10 == 0:
#|             logger.warning("ingest push failing (%d consecutive)", _push_consec_fail)
#|     return ok
#| def _push_position(pusher, frame_json: str, offset_health) -> None:
#|     """Ship one 4 Hz position-only frame to central through the same pusher."""
#|     pusher._offset_health = offset_health
#|     try:
#|         pusher.push(frame_json.encode('utf-8'))
#|     except Exception:
#|         logger.exception("position-sample push raised")
#| def _run_loop(session, *, pusher, mirror, channel, find_pid, sleep=time.sleep) -> None:
#|     """The open loop. ``session.tick()`` (the closed Squad tick) returns a"""
#|     while True:
#|         try:
#|             tick = session.tick()
#|             if tick.reattach:
#|                 # Finding the game process is ours; building the reader is the session's.
#|                 try:
#|                     session.attach(find_pid())
#|                 except Exception:
#|                     logger.exception("re-attach failed")
#|                     sleep(session.interval)
#|                     continue
#|                 sleep(tick.sleep_s)
#|                 continue
#|             if tick.snapshot is None:
#|                 sleep(tick.sleep_s)
#|                 continue
#|             try:
#|                 _publish(tick.snapshot, pusher=pusher, mirror=mirror, channel=channel,
#|                          offset_health=session.offset_health)
#|             except Exception:
#|                 logger.exception("publish failed")
#|             cycle_dur = time.time() - tick.cycle_start
#|             logger.info(tick.summary.format(cycle=cycle_dur))
#|             wait = max(0.1, tick.interval_s - cycle_dur)
#|             if tick.sample_positions and pusher is not None:
#|                 for frame_json in session.idle(wait, tick.base_elapsed):
#|                     _push_position(pusher, frame_json, session.offset_health)
#|             else:
#|                 sleep(wait)
#|         except KeyboardInterrupt:
#|             logger.info("Stopped by user (KeyboardInterrupt).")
#|             break
#| class _QueueHook:
#|     """Queue priority rides the session: it acts before each read, annotates the"""
#|     def __init__(self, enforcer):
#|         self.enforcer = enforcer
#|     def before(self, is_new_match: bool) -> None:
#|         try:
#|             self.enforcer.enforce(is_new_match=is_new_match)
#|         except Exception:
#|             logger.exception('queue_priority enforce failed')
#|     def after(self, snapshot: dict) -> None:
#|         # The enforcer lives in THIS process; the server is separate, so the
#|         try:
#|             snapshot['queuePriority'] = self.enforcer.status()
#|         except Exception:
#|             pass
#|     def on_attach(self, reader) -> None:
#|         try:
#|             self.enforcer.attach_reader(reader)
#|         except Exception:
#|             logger.exception("queue_priority attach_reader failed")
#|         try:
#|             reader._queue_enforcer = self.enforcer       # the admin status endpoint reads it
#|         except (AttributeError, TypeError):
#|             logger.exception("queue_priority enforcer rebind failed")
#| def main():
#|     # Self-install bootstrap. When ``--install`` is on argv we act as a
#|     if "--install" in sys.argv:
#|         # Minimal stderr logging so the operator can see progress.
#|         logging.basicConfig(
#|             level=logging.INFO,
#|             format="[install] %(message)s",
#|             stream=sys.stderr,
#|         )
#|         try:
#|             from agent._install import install_linux, InstallError, _print_error_banner
#|         except ImportError as exc:
#|             logger.error("self-install unavailable on this build: %s", exc)
#|             sys.exit(7)
#|         token       = _extract_argv_value("--enroll")
#|         force_user  = _extract_argv_value("--force-user")
#|         deploy_dir  = _extract_argv_value("--deploy-dir")
#|         try:
#|             rc = install_linux(
#|                 enroll_token=token,
#|                 deploy_dir=Path(deploy_dir) if deploy_dir else None,
#|                 force_user=force_user,
#|                 accept_legal="--accept-legal" in sys.argv,
#|                 autostart="--no-autostart" not in sys.argv,
#|             )
#|         except InstallError as exc:
#|             _print_error_banner(exc)
#|             sys.exit(7)
#|         sys.exit(rc)
#|     # ``--enroll-only`` signals "write .env.agent and exit". Used by the
#|     _enroll_only_requested = "--enroll-only" in sys.argv
#|     if _enroll_only_requested:
#|         # Strip it so argparse never sees it (we'd exit before argparse
#|         sys.argv = [a for a in sys.argv if a != "--enroll-only"]
#|     # Self-enrollment bootstrap. Runs only when:
#|     try:
#|         from agent._enroll import bootstrap_if_needed as _enroll_run
#|         if _enroll_run():
#|             # New env file written — re-load so SQUAD_PUSH_URL etc.
#|             _auto_load_env_files()
#|     except ImportError:
#|         pass
#|     if _enroll_only_requested:
#|         # Exit unconditionally — even when bootstrap_if_needed() returned
#|         logger.info("--enroll-only set; exiting (enrollment skipped if "
#|                      ".env.agent already present)")
#|         sys.exit(0)
#|     parser = argparse.ArgumentParser(description='SquadReplay Agent')
#|     str_, int_ = str, int
#|     for flag, kw in (
#|         ('--interval', dict(type=int_, help='Seconds between ticks (default 1 with --push, else 5)')),
#|         ('--output', dict(type=str_, default='squad_live_data.json', help='Local JSON copy of the latest snapshot')),
#|         ('--log-level', dict(type=str_, default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging verbosity')),
#|         ('--log-file', dict(type=str_, help='Also write the log to this file')),
#|         ('--no-mmap', dict(action='store_true', help='No shared-memory copy, JSON file only')),
#|         ('--mmap-capacity', dict(type=int_, default=DEFAULT_CAPACITY, help='Shared-memory size in bytes (grows on overflow)')),
#|         ('--local-db', dict(type=str_, default='player-stats.sqlite', metavar='PATH', help='Local SQLite copy of the match stats')),
#|         ('--no-local-db', dict(action='store_true', help='Do not keep the local player-stats.sqlite')),
#|         ('--push', dict(type=str_, metavar='URL', help='Central server URL (needs --agent-id and a secret)')),
#|         ('--agent-id', dict(type=str_, help='Agent id registered at central (or env SQUAD_AGENT_ID)')),
#|         ('--secret-hex', dict(type=str_, help='Agent secret in hex (or env SQUAD_AGENT_SECRET_HEX)')),
#|         ('--seq-state', dict(type=str_, help='File for the push sequence counter (default <output>.push.seq)')),
#|         # The --install family is handled before argparse runs (top of main); listed here for --help.
#|         ('--no-autostart', dict(action='store_true', help='With --install: no cron @reboot entry')),
#|         ('--install', dict(action='store_true', help='One-time Linux install as root (sysctl, start.sh, cron, enroll)')),
#|         ('--force-user', dict(type=str_, metavar='USER', help='With --install: the Squad service user, if not auto-detected')),
#|         ('--deploy-dir', dict(type=str_, metavar='PATH', help='With --install: where to install')),
#|         ('--enroll', dict(type=str_, metavar='TOKEN', help='One-time enrollment token from central')),
#|         ('--pid', dict(type=int_, help='Attach to this game PID (also disables the orphan killer)')),
#|         ('--no-kill-orphans', dict(action='store_true', help='Do not kill other reader instances at start')),
#|         ('--config', dict(type=str_, help='squad_replay_config.json (executable_path, process_name, attach_retry_seconds)')),
#|     ):
#|         parser.add_argument(flag, **kw)
#|     args = parser.parse_args()
#|     # Zero-arg launch: when .env.agent was auto-loaded it populated
#|     if args.agent_id is None:
#|         args.agent_id = (os.environ.get('SQUAD_AGENT_ID') or '').strip() or None
#|     try:
#|         from agent.updater import _is_packaged, _BAKED_PUSH_URL
#|         _is_packaged_build = _is_packaged()
#|     except ImportError:
#|         _is_packaged_build = False
#|         _BAKED_PUSH_URL = None
#|     if _is_packaged_build and args.agent_id:
#|         env_push = (os.environ.get('SQUAD_PUSH_URL') or '').strip()
#|         if env_push and env_push != _BAKED_PUSH_URL:
#|             logger.warning(
#|                 "Packaged build ignores SQUAD_PUSH_URL=%r — pinned to %s",
#|                 env_push, _BAKED_PUSH_URL,
#|             )
#|         if args.push and args.push != _BAKED_PUSH_URL:
#|             logger.warning(
#|                 "Packaged build ignores --push %r — pinned to %s",
#|                 args.push, _BAKED_PUSH_URL,
#|             )
#|         args.push = _BAKED_PUSH_URL
#|     elif args.push is None:
#|         # Source mode dev path — honor SQUAD_PUSH_URL when --push
#|         args.push = (os.environ.get('SQUAD_PUSH_URL') or '').strip() or None
#|     if args.push and not args.log_file:
#|         args.log_file = 'logs/agent.log'
#|     if args.push and not args.config:
#|         args.config = 'squad_replay_config.json'
#|     # Interval default is mode-sensitive: push/agent mode wants tighter
#|     if args.interval is None:
#|         args.interval = 1 if args.push else 5
#|     # --push validation — fail fast before we connect to the game process
#|     pusher: IngestPusher | None = None
#|     if args.push:
#|         if not args.agent_id:
#|             parser.error("--push requires --agent-id (or env SQUAD_AGENT_ID)")
#|         secret_hex = args.secret_hex or os.environ.get(
#|             'SQUAD_AGENT_SECRET_HEX', ''
#|         )
#|         if not secret_hex:
#|             parser.error(
#|                 "--push requires --secret-hex or env SQUAD_AGENT_SECRET_HEX")
#|         # Wrapped secrets (systemd-creds) decrypt only on the host that
#|         try:
#|             from agent.secret_store import load_secret_from_env_value, SecretStoreError
#|             secret_hex = load_secret_from_env_value(secret_hex)
#|         except ImportError:
#|             pass
#|         except SecretStoreError as exc:
#|             parser.error(
#|                 f"Secret decryption failed ({exc}). The env binding was "
#|                 "sealed on a different user/machine or with a wrapper "
#|                 "this platform doesn't support. Re-provision the secret "
#|                 "on THIS host — see agent/secret_store.py."
#|             )
#|         if not secret_hex:
#|             parser.error("secret unwrapped to empty — env value malformed")
#|         seq_path = Path(
#|             args.seq_state
#|             if args.seq_state is not None
#|             else str(args.output) + '.push.seq'
#|         )
#|         try:
#|             pusher = IngestPusher(
#|                 url=args.push,
#|                 agent_id=args.agent_id,
#|                 secret_hex=secret_hex,
#|                 seq_state_path=seq_path,
#|             )
#|         except (ValueError, RuntimeError) as e:
#|             parser.error(str(e))
#|     _configure_logging(args.log_level, args.log_file)
#|     # Kill orphaned instances from prior pm2 restarts before acquiring any
#|     if args.pid is not None or args.no_kill_orphans:
#|         logger.info(
#|             "Orphan-reader killer disabled (--pid=%s, --no-kill-orphans=%s)",
#|             args.pid, args.no_kill_orphans,
#|         )
#|     else:
#|         killed = kill_previous_instances("squad_memory_reader.py")
#|         if killed:
#|             logger.info("Cleaned up %d orphan instance(s)", killed)
#|     # Runtime offset fetch: when --push is active (agent mode), central
#|     if SquadMemoryReader is None or _sq_session is None:
#|         if pusher is None:
#|             logger.error("The Squad reader is not part of this file, and it "
#|                          "can only be fetched in agent mode (--push).")
#|             sys.exit(2)
#|         _ensure_squad_reader(base_url=args.push, agent_id=args.agent_id,
#|                              agent_secret=pusher.secret)
#|     if pusher is not None:
#|         try:
#|             from agent.offset_client import (
#|                 OffsetFetchError,
#|                 apply_offsets,
#|                 fetch_offsets,
#|             )
#|         except ImportError as exc:
#|             logger.error(
#|                 "offset client unavailable (%s) and agent mode is active — refusing "
#|                 "to run with baked-in offsets. Rebuild the binary with the agent/ "
#|                 "package included.", exc,
#|             )
#|             sys.exit(2)
#|         try:
#|             bundle = fetch_offsets(
#|                 base_url=args.push,
#|                 agent_id=args.agent_id,
#|                 agent_secret=pusher.secret,
#|             )
#|         except OffsetFetchError as exc:
#|             logger.error(
#|                 "offset fetch failed (%s). Agent mode requires a working central "
#|                 "connection — no baked-in fallback. Retry after confirming "
#|                 "--push URL, agent id, and secret are correct.", exc,
#|             )
#|             # Self-heal attempt before giving up: the failure could be
#|             try:
#|                 from agent import updater as _updater
#|                 if _updater.check_and_apply(args.push):
#|                     logger.info(
#|                         "updater: applied a fix during offset-fetch failure "
#|                         "recovery — exiting for restart",
#|                     )
#|                     sys.exit(0)
#|             except ImportError:
#|                 pass
#|             sys.exit(3)
#|         applied = apply_offsets(SquadMemoryReader, bundle)
#|         if not applied:
#|             logger.error(
#|                 "Configuration bundle from central is empty or unrecognised — "
#|                 "refusing to run. Central may be serving a bundle for a "
#|                 "different schema version.",
#|             )
#|             sys.exit(4)
#|         # Same bundle also carries queue_priority's beacon offsets
#|         try:
#|             if not _agent_can_write():
#|                 raise ImportError("read-only variant")
#|             _ensure_write_payload(base_url=args.push, agent_id=args.agent_id,
#|                                   agent_secret=pusher.secret)
#|             import queue_priority as _queue_priority_offsets_mod
#|             qp_applied = apply_offsets(_queue_priority_offsets_mod, bundle)
#|             if qp_applied:
#|                 logger.debug(
#|                     "queue_priority offsets applied (%d entries)",
#|                     len(qp_applied),
#|                 )
#|             else:
#|                 logger.warning(
#|                     "queue_priority offsets missing from bundle — plugin "
#|                     "will run with stripped (zeroed) defaults until "
#|                     "central serves an updated bundle",
#|                 )
#|         except ImportError as exc:
#|             if _agent_can_write():
#|                 logger.warning("queue_priority module unavailable for offset "
#|                                "patch: %s", exc)
#|         logger.info(
#|             "Configuration applied (%d entries) — service ready",
#|             len(applied),
#|         )
#|         logger.debug(
#|             "diag: 'VEH_ENGINE_ACTIVE' in applied: %s",
#|             'VEH_ENGINE_ACTIVE' in applied,
#|         )
#|         # Binary auto-update — background thread polls central's signed
#|         try:
#|             import threading as _threading
#|             from agent import updater as _updater
#|             _updater_stop = _threading.Event()
#|             _updater_thread = _threading.Thread(
#|                 target=_updater.run_background,
#|                 args=(args.push, _updater_stop),
#|                 name='squad_agent-updater',
#|                 daemon=True,
#|             )
#|             _updater_thread.start()
#|             logger.info(
#|                 "updater thread started (first check in 60s, interval %ds, "
#|                 "target=%s/agent/manifest)",
#|                 _updater.CHECK_INTERVAL_SECONDS, args.push.rstrip('/'),
#|             )
#|         except ImportError as exc:
#|             logger.warning("updater unavailable (%s) — auto-update disabled", exc)
#|         # The manager's Logs / Restart buttons: poll central every 30 s for a queued command.
#|         from agent import control_client as _control
#|         _threading.Thread(
#|             target=_control.run_background, name='squad_agent-control', daemon=True,
#|             kwargs=dict(base_url=args.push, agent_id=args.agent_id, agent_secret=pusher.secret,
#|                         log_path=args.log_file, restart=_restart_agent),
#|         ).start()
#|     # Attach strategy:
#|     reader_config = load_reader_config(
#|         Path(args.config) if args.config else None
#|     )
#|     # Boot banner — the first log line operators see, identifies the
#|     try:
#|         from agent.updater import AGENT_VERSION as _AV
#|         logger.info("SquadReplay binary version: %s (variant: %s)",
#|                     _AV, _agent_variant_name())
#|     except ImportError:
#|         logger.info("SquadReplay binary version: (agent.updater unavailable)")
#|     session = _sq_session.Session(
#|         interval=args.interval,
#|         allow_reattach=args.pid is None,    # an explicit --pid never re-discovers
#|         is_pid_alive=_is_pid_alive,
#|     )
#|     if args.pid is not None:
#|         logger.info("Connecting to service (explicit)...")
#|         current_pid = args.pid
#|     else:
#|         logger.info(
#|             "Auto-attach mode (retry=%ds)",
#|             reader_config.get("attach_retry_seconds", 5),
#|         )
#|         current_pid = wait_for_squad_pid(reader_config)
#|     session.attach(current_pid)
#|     # A voice variant also captures in-game voice: it loads the signed voice
#|     try:
#|         import agent._runtime as _rt
#|         import agent.capabilities as _caps
#|         if (args.push and pusher is not None and _rt.is_bundle()
#|                 and _caps.VOICE in _caps.detect()):
#|             import threading as _vthread
#|             from agent.voice_run import run_remote_capture
#|             _vsock = (os.environ.get('SQUAD_VOICE_SOCK')
#|                       or '/run/squadvoice/%s.sock' % (args.agent_id or 'agent'))
#|             # The game server is restarted now and then (squad1: every morning).
#|             _voice_pid_source = (None if args.pid is not None
#|                                  else (lambda: discover_squad_pid(reader_config)))
#|             def _voice_boot(_pid):
#|                 try:
#|                     run_remote_capture(base_url=args.push, agent_id=args.agent_id,
#|                                        secret=pusher.secret, pid=_pid,
#|                                        sock_path=_vsock,
#|                                        pid_source=_voice_pid_source)
#|                 except Exception:
#|                     logger.exception("voice: capture thread crashed (non-fatal)")
#|             _vthread.Thread(target=_voice_boot, args=(current_pid,),
#|                             daemon=True, name='squad-voice').start()
#|             logger.info("voice: capture thread started (this variant has voice)")
#|     except Exception:
#|         logger.exception("voice: auto-start failed (non-fatal)")
#|     # Shared-memory channel: readers (HTTP server) mmap this file, so every
#|     channel = _LocalChannel(args.output, use_mmap=not args.no_mmap,
#|                             capacity=args.mmap_capacity)
#|     # Local player-stats.sqlite: every snapshot pushed below is also folded
#|     local_mirror = None
#|     if not args.no_local_db:
#|         from agent.local_mirror import LocalMirror
#|         local_mirror = LocalMirror(args.local_db, server_id=args.agent_id)
#|         import atexit
#|         atexit.register(local_mirror.close)
#|     # Tune the cyclic GC for the reader's allocation workload. Each tick
#|     gc.set_threshold(70000, 100, 100)
#|     # Optional queue-priority enforcer. In agent mode (--push) it fetches
#|     if not _agent_can_write():
#|         logger.info("Read-only agent: queue priority is not part of this "
#|                     "build; nothing here writes to the game process.")
#|     else:
#|         try:
#|             from queue_priority import QueuePriority
#|             enforcer = QueuePriority(
#|                 session.reader,
#|                 push_url=(args.push if pusher is not None else None),
#|                 agent_id=(args.agent_id if pusher is not None else None),
#|                 agent_secret=(pusher.secret if pusher is not None else None),
#|             )
#|             session.reader._queue_enforcer = enforcer     # admin status endpoint
#|             session.add_hook(_QueueHook(enforcer))
#|         except Exception as _e:
#|             logger.warning("queue_priority plugin unavailable: %s", _e)
#|     _run_loop(session, pusher=pusher, mirror=local_mirror, channel=channel,
#|               find_pid=lambda: wait_for_squad_pid(reader_config))
#| def _dump_crash_log(exc: BaseException) -> str | None:
#|     """Write a per-crash forensic log so post-mortem doesn't depend on"""
#|     try:
#|         from datetime import datetime, timezone as _tz
#|         ts = datetime.now(_tz.utc).strftime("%Y-%m-%d_%H%M%S")
#|         logs_dir = Path("logs") / "crashes"
#|         logs_dir.mkdir(parents=True, exist_ok=True)
#|         # Filename uses the *public* name so the directory listing
#|         path = logs_dir / f"crash_{ts}_{_public_exc_name(type(exc))}.log"
#|         # Lazy import — keeps the unhappy path from triggering a heavy
#|         import platform
#|         import traceback
#|         try:
#|             from agent.updater import AGENT_VERSION
#|         except ImportError:
#|             AGENT_VERSION = "unknown"
#|         with open(path, "w", encoding="utf-8") as fh:
#|             fh.write(f"=== SquadReplay crash dump ===\n")
#|             fh.write(f"Timestamp UTC:       {ts}\n")
#|             fh.write(f"Agent version:       {AGENT_VERSION}\n")
#|             fh.write(f"Python:              {sys.version.split()[0]}\n")
#|             fh.write(f"Platform:            {platform.platform()}\n")
#|             fh.write(f"PID:                 {os.getpid()}\n")
#|             fh.write(f"argv:                {sys.argv!r}\n")
#|             fh.write(f"cwd:                 {os.getcwd()}\n")
#|             # Memory pressure indicator — useful when the crash was
#|             try:
#|                 import resource  # POSIX
#|                 ru = resource.getrusage(resource.RUSAGE_SELF)
#|                 fh.write(f"max RSS (KB):        {ru.ru_maxrss}\n")
#|             except ImportError:
#|                 pass
#|             fh.write("\n--- Exception ---\n")
#|             fh.write(f"Type:    {type(exc).__name__}\n")
#|             fh.write(f"Repr:    {exc!r}\n\n")
#|             fh.write("--- Traceback ---\n")
#|             # limit=1000 bypasses sys.tracebacklimit=0 (set globally for
#|             fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=1000)))
#|         return str(path)
#|     except OSError:
#|         return None
#| # Exit codes that mean "configuration is broken — restarting won't help".
#| _NORESTART_EXIT_CODES = frozenset({2, 3, 4, 7})
#| # Circuit breaker — if the reader keeps crashing this many times in a
#| _MAX_CONSECUTIVE_CRASHES = 50
#| # A clean run for this long resets the consecutive-crash counter, so a
#| _HEALTHY_RUN_THRESHOLD_SECONDS = 60.0
#| def _supervised_main() -> int:
#|     """Auto-restart wrapper around :func:`main`."""
#|     consecutive_crashes = 0
#|     total_restarts = 0
#|     while True:
#|         run_started = time.time()
#|         # F6: expose restart telemetry to the push layer so the central
#|         os.environ['SQUAD_AGENT_RESTARTS'] = str(total_restarts)
#|         os.environ['SQUAD_AGENT_CONSEC_CRASHES'] = str(consecutive_crashes)
#|         try:
#|             main()
#|             return 0  # main() returned normally → clean exit
#|         except KeyboardInterrupt:
#|             logger.info("KeyboardInterrupt — clean exit")
#|             return 0
#|         except SystemExit as e:
#|             code = e.code if isinstance(e.code, int) else 1
#|             # Code 0 = explicit clean exit. One-shot helper modes
#|             if code == 0:
#|                 return 0
#|             if code in _NORESTART_EXIT_CODES:
#|                 logger.error(
#|                     "Service exited with terminal code %s — restart would "
#|                     "not help. Operator intervention required.", code,
#|                 )
#|                 return code
#|             consecutive_crashes += 1
#|             total_restarts += 1
#|             logger.warning(
#|                 "Service exited with code %s (transient) — will restart. "
#|                 "consecutive_crashes=%d", code, consecutive_crashes,
#|             )
#|         except BaseException as exc:  # noqa: BLE001 — supervisor catch-all
#|             consecutive_crashes += 1
#|             total_restarts += 1
#|             run_dur = time.time() - run_started
#|             crash_path = _dump_crash_log(exc)
#|             # Public-facing name only; internal class identifier
#|             logger.error(
#|                 "Service error %s after %.1fs of runtime — restart #%d. Dump: %s",
#|                 _public_exc_name(type(exc)), run_dur, consecutive_crashes,
#|                 crash_path or "<dump failed>",
#|             )
#|             # If the run lasted long enough to be considered "healthy",
#|             if run_dur >= _HEALTHY_RUN_THRESHOLD_SECONDS:
#|                 consecutive_crashes = 1
#|         if consecutive_crashes >= _MAX_CONSECUTIVE_CRASHES:
#|             logger.fatal(
#|                 "Reader crashed %d times in a row without a healthy run "
#|                 "(>=%ds). Giving up — fix the deploy and restart manually.",
#|                 consecutive_crashes, int(_HEALTHY_RUN_THRESHOLD_SECONDS),
#|             )
#|             return 1
#|         # Exponential backoff capped at 60s. Sequence: 2, 4, 8, 16, 32,
#|         delay = min(60, 2 ** min(consecutive_crashes, 6))
#|         logger.info("Restarting service in %ds", delay)
#|         try:
#|             time.sleep(delay)
#|         except KeyboardInterrupt:
#|             logger.info("KeyboardInterrupt during backoff — clean exit")
#|             return 0
#| if __name__ == '__main__':
#|     sys.exit(_supervised_main())
#| ===== package: voice =====
#| ===== module: voice.ogg_opus =====
#| """Wrap pre-encoded Opus frames in an Ogg container (RFC 7845), no re-encode."""
#| import struct
#| # Ogg's CRC-32: generator polynomial, 32-bit mask, bit-31 test. Written as
#| _CRC_POLY = 79764919          # the Ogg CRC-32 generator polynomial
#| _U32 = 4294967295             # 32-bit mask
#| _U32_SIGN = 2147483648        # bit 31
#| def _crc_table():
#|     t = []
#|     for n in range(256):
#|         c = (n << 24) & _U32
#|         for _ in range(8):
#|             if c & _U32_SIGN:
#|                 c = ((c << 1) ^ _CRC_POLY) & _U32
#|             else:
#|                 c = (c << 1) & _U32
#|         t.append(c)
#|     return t
#| _CRC = _crc_table()
#| def ogg_crc32(data: bytes) -> int:
#|     """Ogg's CRC32 (no reflection, init 0, xorout 0)."""
#|     c = 0
#|     for b in data:
#|         c = ((c << 8) & _U32) ^ _CRC[((c >> 24) & 0xff) ^ b]
#|     return c
#| def _seg_table(length: int) -> bytes:
#|     return bytes([255] * (length // 255) + [length % 255])
#| def _page(serial: int, seq: int, granule: int, htype: int, packet: bytes) -> bytes:
#|     segs = _seg_table(len(packet))
#|     head = bytearray(b"OggS")
#|     head += bytes([0, htype])
#|     head += struct.pack("<q", granule)
#|     head += struct.pack("<I", serial)
#|     head += struct.pack("<I", seq)
#|     head += b"\x00\x00\x00\x00"        # CRC placeholder
#|     head += bytes([len(segs)])
#|     head += segs
#|     page = bytes(head) + packet
#|     crc = ogg_crc32(page)
#|     return page[:22] + struct.pack("<I", crc) + page[26:]
#| def _opus_head(pre_skip: int) -> bytes:
#|     return (b"OpusHead" + bytes([1, 1]) + struct.pack("<H", pre_skip)
#|             + struct.pack("<I", 48000) + struct.pack("<h", 0) + bytes([0]))
#| def _opus_tags() -> bytes:
#|     vendor = b"squadreplay"
#|     return b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
#| # RFC 6716 3.1: frame size in 48 kHz samples by TOC config (TOC >> 3).
#| _CONFIG_SAMPLES = ([480, 960, 1920, 2880] * 3          # 0-11 SILK: 10/20/40/60 ms
#|                    + [480, 960] * 2                    # 12-15 hybrid: 10/20 ms
#|                    + [120, 240, 480, 960] * 4)         # 16-31 CELT: 2.5/5/10/20 ms
#| def opus_packet_samples(packet: bytes) -> int:
#|     """Samples (48 kHz) one Opus packet decodes to, from its own TOC byte:"""
#|     if not packet:
#|         return 0
#|     toc = packet[0]
#|     code = toc & 3
#|     frames = 1 if code == 0 else 2 if code in (1, 2) else (packet[1] & 0x3F if len(packet) > 1 else 0)
#|     return _CONFIG_SAMPLES[toc >> 3] * frames
#| def ogg_opus_mux(frames, serial: int = 1, pre_skip: int = 0) -> bytes:
#|     """Return a complete Ogg-Opus stream carrying ``frames`` in order."""
#|     out = bytearray()
#|     out += _page(serial, 0, 0, 0x02, _opus_head(pre_skip))
#|     out += _page(serial, 1, 0, 0x00, _opus_tags())
#|     granule = 0
#|     for i, f in enumerate(frames):
#|         granule += opus_packet_samples(f)
#|         htype = 0x04 if i == len(frames) - 1 else 0x00
#|         out += _page(serial, i + 2, granule, htype, f)
#|     return bytes(out)
#| ===== module: voice.sender_map =====
#| """Resolve the voice packet's speaker field to an eosId by EXACT pointer"""
#| import time
#| from reflection_resolver import get_class_layout_full
#| def unique_id_offset(reader):
#|     """Reflected byte offset of the player-state UniqueID field (FUniqueNetIdRepl)."""
#|     info = get_class_layout_full(reader, getattr(reader, "sqps_class", None)).get("UniqueID")
#|     return info.offset if info else None
#| class SenderMap:
#|     def __init__(self):
#|         self._by_ptr = {}      # uniqueId object ptr -> (eosId, name)
#|     def _uid_obj_ptr(self, reader, ps_ptr):
#|         off = unique_id_offset(reader)
#|         if off is None:
#|             return 0
#|         try:
#|             return reader._r64(ps_ptr + off + 0x8)
#|         except Exception:
#|             return 0
#|     def refresh(self, reader):
#|         off = unique_id_offset(reader)
#|         if off is None:
#|             return
#|         by_ptr = {}
#|         for ps in reader._collect_objects().get("players", []):
#|             try:
#|                 obj = self._uid_obj_ptr(reader, ps)
#|                 if not obj:
#|                     continue
#|                 by_ptr[obj] = (reader._read_eos_id(ps),
#|                                reader.read_fstring(ps + reader.PS_PLAYERNAME))
#|             except Exception:
#|                 continue
#|         self._by_ptr = by_ptr
#|     # An unknown pointer re-reads every PlayerState; with a full server's
#|     REFRESH_MIN_S = 2.0
#|     def lookup(self, reader, sender_ptr):
#|         if sender_ptr in self._by_ptr:
#|             return self._by_ptr[sender_ptr]
#|         now = time.monotonic()
#|         if now - getattr(self, "_last_refresh", -1e9) >= self.REFRESH_MIN_S:
#|             self._last_refresh = now
#|             self.refresh(reader)      # a reconnect moved the pointer
#|         return self._by_ptr.get(sender_ptr, (None, None))
#| ===== module: voice.track =====
#| """Per-match voice-track: a manifest JSON plus one Ogg-Opus clip file per"""
#| import json
#| import os
#| class VoiceTrack:
#|     def __init__(self, dir_path: str, match_key: str):
#|         self.manifest_path = os.path.join(dir_path, match_key + ".voice.json")
#|         self.clip_dir = os.path.join(dir_path, match_key + ".voice")
#|         os.makedirs(self.clip_dir, exist_ok=True)
#|         self._utterances = []
#|         self.dirty = False
#|         if os.path.exists(self.manifest_path):
#|             try:
#|                 with open(self.manifest_path) as fh:
#|                     self._utterances = json.load(fh)["utterances"]
#|             except (OSError, ValueError, KeyError):
#|                 self._utterances = []
#|         self._ids = {self.identity(u) for u in self._utterances}
#|         self._names = {u.get("clip") for u in self._utterances}
#|     @staticmethod
#|     def identity(u: dict):
#|         """What makes an utterance THE SAME utterance: who, where, when. Not its"""
#|         return (u.get("eosId"), u.get("channel"), u.get("startElapsed"), u.get("endElapsed"))
#|     def place(self, u: dict, wanted_name: str):
#|         """The clip name to store ``u`` under, or ``None`` when this utterance is"""
#|         if self.identity(u) in self._ids:
#|             return None
#|         return wanted_name if wanted_name not in self._names else self.next_clip_name()
#|     def write_clip(self, name: str, ogg_bytes: bytes):
#|         with open(os.path.join(self.clip_dir, name + ".opus"), "wb") as fh:
#|             fh.write(ogg_bytes)
#|     def next_clip_name(self) -> str:
#|         """The next unused clip name. Continues after the utterances already"""
#|         n = len(self._utterances)
#|         while ("u%06d" % n in self._names
#|                or os.path.exists(os.path.join(self.clip_dir, "u%06d.opus" % n))):
#|             n += 1
#|         return "u%06d" % n
#|     def append(self, u: dict, clip_name: str, save: bool = True):
#|         self._utterances.append({
#|             "eosId": u["eosId"], "displayName": u.get("displayName"),
#|             "channel": u["channel"], "startElapsed": u["startElapsed"],
#|             "endElapsed": u["endElapsed"],
#|             "dur": round(u["endElapsed"] - u["startElapsed"], 3), "clip": clip_name,
#|         })
#|         self._ids.add(self.identity(u))
#|         self._names.add(clip_name)
#|         self.dirty = True
#|         if save:
#|             self.save()
#|     def append_if_absent(self, u: dict, clip_name: str, save: bool = False) -> bool:
#|         """Append this utterance only if ``clip_name`` is not already present."""
#|         if any(existing.get("clip") == clip_name for existing in self._utterances):
#|             return False
#|         self.append(u, clip_name, save=save)
#|         return True
#|     def save(self):
#|         """Rewrite the manifest atomically. A full server has many speakers"""
#|         tmp = self.manifest_path + ".tmp"
#|         with open(tmp, "w") as fh:
#|             json.dump({"utterances": self._utterances}, fh)
#|         os.replace(tmp, self.manifest_path)
#|         self.dirty = False
#|     def manifest(self):
#|         return {"utterances": self._utterances}
#| ===== module: voice.utterances =====
#| """Group a stream of attributed voice frames into utterances."""
#| def group_utterances(frames, gap_s: float = 0.4):
#|     utts, cur = [], None
#|     for f in frames:
#|         key = (f["eosId"], f["channel"])
#|         if (cur is None or key != cur["_key"]
#|                 or f["elapsed"] - cur["endElapsed"] > gap_s):
#|             cur = {"_key": key, "eosId": f["eosId"], "channel": f["channel"],
#|                    "startElapsed": f["elapsed"], "endElapsed": f["elapsed"],
#|                    "frames": []}
#|             utts.append(cur)
#|         cur["frames"].append(f["frame"])
#|         cur["endElapsed"] = f["elapsed"]
#|     for u in utts:
#|         del u["_key"]
#|     return utts
