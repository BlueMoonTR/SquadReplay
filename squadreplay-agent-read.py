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
"""
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import linecache
import os
import sys

# ---- filled in by the bundler -------------------------------------------------
_VARIANT = 'read'
_VERSION = '0.85.3'
_BUILT_FROM = '4d10f3ab5673'
_SECTION_SHA256 = 'c26ffc31a1940afa7cbbaaeae360e182d0be95eff658145b78922d9616b72440'
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
#|
#| from __future__ import annotations
#|
#| __all__ = ["offset_client"]
#| ===== module: agent._enroll =====
#| """agent/_enroll.py — Agent self-enrollment bootstrap."""
#| from __future__ import annotations
#|
#| import json
#| import logging
#| import os
#| import sys
#| import urllib.error
#| import urllib.request
#| from pathlib import Path
#|
#| logger = logging.getLogger("squad_agent.enroll")
#|
#| # Where the operator may stash the token. Checked in this order;
#| _TOKEN_ENV_VAR  = "SQUAD_ENROLL_TOKEN"
#| _TOKEN_FILENAME = "enroll.txt"
#| # Default URL the agent calls when nothing better is configured.
#| _DEFAULT_BASE_URL = "https://squadreplay.com"
#| # Connection timeout. The endpoint is fast (single registry write +
#| _HTTP_TIMEOUT_S = 30
#|
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
#|
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
#|
#|     env_token = (os.environ.get(_TOKEN_ENV_VAR) or "").strip()
#|     if env_token:
#|         return env_token, None
#|
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
#|
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
#|
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
#|
#| def bootstrap_if_needed() -> bool:
#|     """Run the enrollment dance once if the install is fresh."""
#|     here = _binary_dir()
#|     env_path = here / ".env.agent"
#|     if env_path.exists():
#|         return False
#|     # Also consider already-loaded process env: an operator using the
#|     if (os.environ.get("SQUAD_AGENT_SECRET_HEX") or "").strip():
#|         return False
#|
#|     token, token_path = _read_token()
#|     if not token:
#|         return False
#|
#|     base_url = (os.environ.get("SQUAD_PUSH_URL") or "").strip() or _DEFAULT_BASE_URL
#|     platform = "linux" if sys.platform.startswith("linux") else sys.platform
#|
#|     logger.info("enroll: contacting %s with platform=%s", base_url, platform)
#|     doc = _post_enroll(base_url, token=token, platform=platform)
#|     if not doc:
#|         return False
#|
#|     agent_id   = str(doc.get("agent_id") or "").strip()
#|     secret_hex = str(doc.get("secret_hex") or "").strip().lower()
#|     push_url   = str(doc.get("push_url") or base_url).strip() or base_url
#|     if not agent_id or len(secret_hex) != 64:
#|         logger.error("enroll: central response missing fields")
#|         return False
#|
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
#|
#|     # Push values into the live env so the rest of the boot flow can
#|     os.environ.setdefault("SQUAD_AGENT_ID", agent_id)
#|     os.environ.setdefault("SQUAD_AGENT_SECRET_HEX", secret_storage)
#|     os.environ.setdefault("SQUAD_PUSH_URL", push_url)
#|
#|     if token_path is not None:
#|         # One-time token. Delete the file so a backup snapshot or
#|         try:
#|             token_path.unlink()
#|         except OSError:
#|             pass
#|
#|     logger.info("enroll OK: agent_id=%s, .env.agent saved at %s",
#|                 agent_id, env_path)
#|     return True
#|
#| __all__ = ["bootstrap_if_needed"]
#| ===== module: agent._install =====
#| """agent/_install.py — Linux self-install bootstrap."""
#| from __future__ import annotations
#|
#| import logging
#| import os
#| import re
#| import shlex
#| import shutil
#| import subprocess
#| import sys
#| from pathlib import Path
#|
#| logger = logging.getLogger("SquadReplay.install")
#|
#| # ---------------------------------------------------------------------------
#|
#| def _ansi(code: str, text: str) -> str:
#|     """Wrap text in an ANSI escape sequence, but only when stdout is a TTY."""
#|     if sys.stdout.isatty():
#|         return f"\033[{code}m{text}\033[0m"
#|     return text
#|
#| def _green(t: str)  -> str: return _ansi("1;92", t)
#| def _red(t: str)    -> str: return _ansi("1;91", t)
#| def _yellow(t: str) -> str: return _ansi("1;93", t)
#| def _bold(t: str)   -> str: return _ansi("1",    t)
#| def _dim(t: str)    -> str: return _ansi("2",    t)
#|
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
#|
#| def _print_success_banner(workdir: Path) -> None:
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
#|     print(_dim(f"  crashes. It does NOT survive reboots — run a screen/tmux"))
#|     print(_dim(f"  session (or your own cron @reboot entry) if you want it"))
#|     print(_dim(f"  back up automatically after a reboot."))
#|     print()
#|     print(_dim(f"  Watch logs:"))
#|     print(_dim(f"    tail -f {workdir}/logs/agent.log"))
#|     print()
#|
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
#|
#| class InstallError(RuntimeError):
#|     """Raised when self-install hits an unrecoverable precondition."""
#|
#| # Standard system paths used by the installer. Constants so a future
#| _SYSCTL_PATH        = Path("/etc/sysctl.d/99-squad-replay.conf")
#| _SUDOERS_VOICE_PATH = Path("/etc/sudoers.d/squad-replay-voice")
#| _DEFAULT_DEPLOY_REL = Path("BOTS") / "SquadReplay"      # under target user's $HOME
#|
#| # ---------------------------------------------------------------------------
#|
#| def _ensure_root() -> None:
#|     """Install touches /etc/sysctl.d and needs setcap — must be root."""
#|     if os.geteuid() != 0:
#|         raise InstallError(
#|             "self-install must run as root (sudo). Re-run with "
#|             "`sudo ./SquadReplay --install [...]`"
#|         )
#|
#| def _ensure_linux() -> None:
#|     if not sys.platform.startswith("linux"):
#|         raise InstallError(
#|             f"self-install supports Linux only (detected: {sys.platform})"
#|         )
#|
#| # ---------------------------------------------------------------------------
#|
#| # Squad server binary name on Linux (without .exe). When multiple
#| _SQUAD_COMM = "SquadGameServer"
#|
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
#|
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
#|
#| # ---------------------------------------------------------------------------
#|
#| _SYSCTL_BODY = """\
#| # SquadReplay agent runtime requirement. Generated by `SquadReplay --install`.
#| kernel.yama.ptrace_scope = 0
#| """
#|
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
#|
#| # ---------------------------------------------------------------------------
#|
#| def _variant_has_voice() -> bool:
#|     """Whether the variant being installed carries the voice plumbing."""
#|     try:
#|         from agent import capabilities
#|         return "voice" in capabilities.detect()
#|     except Exception:
#|         return False
#|
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
#|
#| def _voice_sudoers_body(user: str, tap: Path) -> str:
#|     """The sudoers rule: ``user`` may run exactly ``/usr/bin/python3 <tap>``"""
#|     return (
#|         "# SquadReplay voice capture. Lets the agent run the eBPF voice tap as\n"
#|         "# root (it needs CAP_BPF/CAP_PERFMON) without a password. Generated by\n"
#|         "# `SquadReplay --install`. Remove this file to revoke.\n"
#|         f"{user} ALL=(root) NOPASSWD: /usr/bin/python3 {tap} *\n"
#|     )
#|
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
#|
#| def _maybe_setup_voice_capture(user: str, workdir: Path) -> None:
#|     if not _variant_has_voice():
#|         return
#|     logger.info("voice variant: installing python3-bpfcc + sudo rule for the tap")
#|     _apt_install_bpfcc()
#|     try:
#|         _write_voice_sudoers_dropin(user, workdir)
#|     except OSError as exc:
#|         logger.warning("voice sudoers setup failed (%s); voice needs manual sudo", exc)
#|
#| # ---------------------------------------------------------------------------
#|
#| # The game Port launch arg, not QueryPort: the negative lookbehind rejects a
#| _PORT_RE = re.compile(r"(?<![A-Za-z])Port=(\d+)")
#|
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
#|
#| # ---------------------------------------------------------------------------
#|
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
#|
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
#|
#|     # Nuitka onefile: the child process has sys.executable pointing at
#|     onefile_dir = os.environ.get('NUITKA_ONEFILE_DIRECTORY', '')
#|     if onefile_dir:
#|         current = (Path(onefile_dir) / 'SquadReplay').resolve()
#|     else:
#|         current = Path(sys.executable).resolve()
#|     target = (deploy_dir / "SquadReplay").resolve()
#|     if current == target:
#|         return target
#|     deploy_dir.mkdir(parents=True, exist_ok=True)
#|     shutil.copy2(current, target)
#|     target.chmod(0o755)
#|     logger.info("copied binary to %s", target)
#|     return target
#|
#| _START_SH_BODY = """\
#| #!/usr/bin/env bash
#| set -euo pipefail
#| cd "$(dirname "$0")"
#| # Enrollment computed this host's HW fingerprint as {user} (the service
#| if [ "$(id -un)" = "root" ]; then
#|     exec setpriv --reuid {user} --regid {user} --init-groups --no-new-privs "$(pwd)/$(basename "$0")" "$@"
#| fi
#|
#| if [ -f .env.agent ]; then
#|     set -a; . .env.agent; set +a
#| fi
#|
#| # Tells the auto-update swap helper (agent/updater.py) that WE own
#| export SQUAD_AGENT_SUPERVISED=1
#|
#| mkdir -p logs
#|
#| # Supervisor-level messages (launch/restart/stale-kill) go straight into
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
#| _PERMANENT_RC=" 2 4 5 6 "
#|
#| # set -e must be off for the restart loop — a non-zero agent exit propagates
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
#|
#| def _start_sh_launch(workdir: Path) -> tuple[str, str]:
#|     """``(command to run the agent, name the stale-process sweep looks for)``."""
#|     from agent import _runtime
#|     bundle = _runtime.bundle_path()
#|     if bundle is None:
#|         return "./SquadReplay", "SquadReplay"
#|     py = shlex.quote(_runtime.interpreter())
#|     return f'{py} "$(pwd)/{bundle.name}"', bundle.name
#|
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
#|
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
#|
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
#|
#| def _apply_caps(binary_path: Path) -> None:
#|     """Belt-and-braces — ptrace_scope=0 already lets same-UID attach,"""
#|     from agent import _runtime
#|     if _runtime.is_bundle():
#|         logger.info("single-file agent: no file capabilities (they would "
#|                     "go on the Python interpreter); ptrace comes from the "
#|                     "sysctl drop-in and running as the game's user")
#|         return
#|     try:
#|         subprocess.run(
#|             ["setcap", "cap_sys_ptrace,cap_dac_read_search+eip", str(binary_path)],
#|             check=True, capture_output=True, text=True,
#|         )
#|         logger.info("applied file capabilities to %s", binary_path)
#|     except (subprocess.CalledProcessError, FileNotFoundError) as exc:
#|         # Not fatal — the sysctl drop-in is the primary mechanism.
#|         logger.warning("setcap failed (%s); falling back to sysctl tunable", exc)
#|
#| # ---------------------------------------------------------------------------
#|
#| _USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,32}$")
#|
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
#|
#| # ---------------------------------------------------------------------------
#|
#| def install_linux(
#|     *,
#|     enroll_token: str | None = None,
#|     deploy_dir: Path | None = None,
#|     force_user: str | None = None,
#|     accept_legal: bool = False,
#| ) -> int:
#|     """Run the full Linux self-install. Returns 0 on success or raises"""
#|     _ensure_linux()
#|     _ensure_root()
#|
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
#|
#|     # 2. Place binary into deploy dir under target user's home.
#|     workdir = _resolve_deploy_dir(target_user, deploy_dir)
#|
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
#|
#|     workdir.mkdir(parents=True, exist_ok=True)
#|     (workdir / "logs").mkdir(exist_ok=True)
#|     # No replays/ dir: a pushing agent never writes replays locally -- central
#|     binary = _self_copy_to_deploy(workdir)
#|     _write_start_sh(workdir, target_user)
#|     _chown_recursive(workdir, target_user)
#|
#|     # 3. Apply ptrace permissions (primary: sysctl drop-in; secondary: file caps).
#|     _write_sysctl_dropin()
#|     _apply_caps(binary)
#|
#|     # 3b. Voice variants need python3-bpfcc + passwordless sudo for the eBPF
#|     _maybe_setup_voice_capture(target_user, workdir)
#|
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
#|
#|     # 4b. player-stats.sqlite: the community's own copy of every match's
#|     _create_local_stats_db(workdir, target_user)
#|
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
#|
#|     _print_success_banner(workdir)
#|     return 0
#|
#| __all__ = ["install_linux", "InstallError", "_print_error_banner"]
#| ===== module: agent._legal =====
#| """agent/_legal.py — show the legal notice and record that it was accepted."""
#| from __future__ import annotations
#|
#| import json
#| import time
#| from pathlib import Path
#| from typing import Callable
#|
#| #: Bump when the notice changes materially; it re-prompts existing installs.
#| NOTICE_VERSION = 1
#|
#| #: What the person has to type. Not "y": a reflex keystroke is not consent.
#| PHRASE = "I ACCEPT"
#|
#| LEGAL_URL = "https://github.com/BlueMoonTR/SquadReplay/blob/main/LEGAL.md"
#|
#| ACCEPTANCE_FILE = "legal_accepted.json"
#|
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
#|
#| class LegalNotAccepted(RuntimeError):
#|     """The notice was not accepted; the install must not continue."""
#|
#| def accepted_version(workdir: Path) -> int | None:
#|     """The notice version recorded in ``workdir``, or None."""
#|     try:
#|         doc = json.loads((Path(workdir) / ACCEPTANCE_FILE).read_text(encoding="utf-8"))
#|         v = doc.get("notice_version")
#|         return v if isinstance(v, int) and not isinstance(v, bool) else None
#|     except (OSError, ValueError, AttributeError):
#|         return None
#|
#| def already_accepted(workdir: Path) -> bool:
#|     """True when this install has accepted the CURRENT notice."""
#|     v = accepted_version(workdir)
#|     return v is not None and v >= NOTICE_VERSION
#|
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
#|
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
#|
#|     out(NOTICE)
#|
#|     if accept_flag:
#|         _record(workdir, "flag", who)
#|         out("Legal notice accepted with --accept-legal.")
#|         return True
#|
#|     if not interactive:
#|         raise LegalNotAccepted(
#|             "The legal notice above has not been accepted, and there is no "
#|             "terminal to ask on. Read it, then re-run with --accept-legal "
#|             "if you accept it."
#|         )
#|
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
#|
#| __all__ = [
#|     "ACCEPTANCE_FILE", "LEGAL_URL", "NOTICE", "NOTICE_VERSION", "PHRASE",
#|     "LegalNotAccepted", "accepted_version", "already_accepted",
#|     "require_acceptance",
#| ]
#| ===== module: agent._platform =====
#| """agent/_platform.py — Linux process shims for the agent."""
#|
#| from __future__ import annotations
#|
#| import logging
#| import os
#| import sys
#| from pathlib import Path
#|
#| logger = logging.getLogger("squad_agent.platform")
#|
#| IS_LINUX = sys.platform.startswith("linux")
#|
#| # ---------------------------------------------------------------------------
#|
#| def find_pid(image_name: str, executable_path: str | None = None,
#|              match_cmdline: str | None = None) -> int | None:
#|     """Return the PID of a running process matching ``image_name``."""
#|     if IS_LINUX:
#|         return _find_pid_linux(image_name, executable_path, match_cmdline)
#|     raise NotImplementedError(f"find_pid: unsupported platform {sys.platform}")
#|
#| def _find_pid_linux(image_name: str, executable_path: str | None,
#|                     match_cmdline: str | None = None) -> int | None:
#|     """Walk ``/proc`` and match on ``comm`` + ``exe`` symlink + cmdline."""
#|     target_comm = image_name
#|     if target_comm.endswith(".exe"):
#|         target_comm = target_comm[:-4]
#|     target_comm = target_comm[:15]  # kernel truncates comm to 16 bytes incl. NUL
#|     target_path = str(Path(executable_path).resolve()) if executable_path else None
#|     cmd_needle = (match_cmdline or "").strip() or None
#|
#|     proc_root = Path("/proc")
#|     try:
#|         pid_dirs = [p for p in proc_root.iterdir() if p.name.isdigit()]
#|     except OSError as e:
#|         logger.warning("cannot read /proc: %s", e)
#|         return None
#|
#|     # Two-phase candidate collection:
#|
#|     exact_candidates: list[int] = []
#|     inode_candidates: list[int] = []
#|
#|     # Resolve target inode once (avoid repeated stat inside the loop)
#|     tgt_ino: tuple[int, int] | None = None
#|     if target_path is not None:
#|         try:
#|             s = os.stat(target_path)
#|             tgt_ino = (s.st_ino, s.st_dev)
#|         except OSError:
#|             pass  # target doesn't exist; inode match impossible
#|
#|     for pid_dir in pid_dirs:
#|         try:
#|             comm = (pid_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
#|         except OSError:
#|             continue
#|         if comm != target_comm:
#|             continue
#|
#|         if target_path is not None:
#|             try:
#|                 exe_real = os.readlink(pid_dir / "exe")
#|             except OSError:
#|                 continue
#|
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
#|
#|     # Prefer exact matches; fall back to inode matches.
#|     candidates = exact_candidates if exact_candidates else inode_candidates
#|
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
#|
#|     if not candidates:
#|         return None
#|
#|     if len(candidates) > 1 and not inode_candidates:
#|         # Multiple exact matches — unusual but return first silently.
#|         return candidates[0]
#|
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
#|
#|     return candidates[0]
#|
#| # ---------------------------------------------------------------------------
#|
#| def is_pid_alive(pid: int | None) -> bool:
#|     """True when ``pid`` maps to a running process on this host."""
#|     if not pid or pid <= 0:
#|         return False
#|     if IS_LINUX:
#|         return _is_pid_alive_linux(pid)
#|     raise NotImplementedError(f"is_pid_alive: unsupported platform {sys.platform}")
#|
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
#|
#| # ---------------------------------------------------------------------------
#|
#| def list_processes_by_name(image_name: str) -> list[tuple[int, str]]:
#|     """Return (pid, command_line) pairs for every running process whose"""
#|     if IS_LINUX:
#|         return _list_processes_linux(image_name)
#|     raise NotImplementedError(
#|         f"list_processes_by_name: unsupported platform {sys.platform}"
#|     )
#|
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
#|
#| __all__ = [
#|     "IS_LINUX",
#|     "find_pid",
#|     "is_pid_alive",
#|     "list_processes_by_name",
#| ]
#| ===== module: agent._runtime =====
#| """agent/_runtime.py -- is this process a downloaded single-file variant?"""
#| from __future__ import annotations
#|
#| import os
#| import sys
#| from pathlib import Path
#|
#| BUNDLE_ENV = "SQUADREPLAY_BUNDLE"
#|
#| # Where a voice variant materialises the eBPF tap so the root system-python
#| VOICE_TAP_FILENAME = "squadreplay-voice-tap.py"
#|
#| def voice_tap_path() -> Path | None:
#|     """The on-disk path the voice tap is extracted to, or None when this is"""
#|     b = bundle_path()
#|     return (b.parent / VOICE_TAP_FILENAME) if b else None
#|
#| def bundle_path() -> Path | None:
#|     """The running single-file agent, or None when this is not one."""
#|     raw = os.environ.get(BUNDLE_ENV)
#|     if not raw:
#|         return None
#|     p = Path(raw)
#|     return p if p.is_file() else None
#|
#| def is_bundle() -> bool:
#|     return bundle_path() is not None
#|
#| def interpreter() -> str:
#|     """The Python that runs the bundle -- what a relaunch must start."""
#|     return sys.executable or "python3"
#|
#| def relaunch_argv(path: Path) -> list[str]:
#|     """The command that starts ``path`` again: the interpreter and the file"""
#|     if is_bundle():
#|         return [interpreter(), str(path)]
#|     return [str(path)]
#|
#| __all__ = ["BUNDLE_ENV", "VOICE_TAP_FILENAME", "bundle_path", "interpreter",
#|            "is_bundle", "relaunch_argv", "voice_tap_path"]
#| ===== module: agent.capabilities =====
#| """agent/capabilities.py — what this agent build can actually do."""
#| from __future__ import annotations
#|
#| import functools
#| import importlib
#|
#| READ = "read"
#| WRITE = "write"
#| VOICE = "voice"
#|
#| def _importable(name: str) -> bool:
#|     try:
#|         importlib.import_module(name)
#|     except ImportError:
#|         return False
#|     return True
#|
#| @functools.lru_cache(maxsize=1)
#| def detect() -> tuple[str, ...]:
#|     """The capabilities this build carries, in a stable order. Cached:"""
#|     caps = [READ]
#|     return tuple(caps)
#|
#| def header_value(caps: tuple[str, ...] | None = None) -> str:
#|     """``read,write`` -- the X-Agent-Capabilities header."""
#|     return ",".join(caps if caps is not None else detect())
#|
#| def variant_name(caps: tuple[str, ...] | None = None) -> str:
#|     """``read`` / ``read-write`` -- the name the release files use."""
#|     return "-".join(caps if caps is not None else detect())
#| ===== module: agent.local_db =====
#| """agent/local_db.py -- the community's own copy of its match stats."""
#| from __future__ import annotations
#|
#| import json
#| import os
#| import sqlite3
#| from pathlib import Path
#| from typing import Any
#|
#| DEFAULT_FILENAME = "player-stats.sqlite"
#| SCHEMA_VERSION = 3   # 2: voice_*_s, 3: sl_squad_objective
#|
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
#| )
#|
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
#|
#| VEHICLE_SESSION = (
#|     ("eos_id", "TEXT"),
#|     ("vehicle_class", "TEXT"),
#|     ("seat", "INTEGER"),
#|     ("entered_at_s", "INTEGER"),
#|     ("exited_at_s", "INTEGER"),
#|     ("distance_m", "REAL"),
#|     ("kills_in_seat", "INTEGER"),
#| )
#|
#| def _cols(spec) -> str:
#|     return ",\n    ".join(f"{name} {typ}" for name, typ in spec)
#|
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
#|
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
#|
#| def _add_missing_columns(conn: sqlite3.Connection, table: str, spec) -> None:
#|     """Bring a file made by an older agent up to this schema: CREATE TABLE"""
#|     have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
#|     for name, typ in spec:
#|         if name not in have:
#|             conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} "
#|                          f"{typ.replace(' NOT NULL', '')}")
#|
#| def _insert_sql(table: str, spec) -> str:
#|     names = ["match_id"] + [n for n, _ in spec]
#|     return (f"INSERT INTO {table} ({', '.join(names)}) "
#|             f"VALUES ({', '.join('?' * len(names))})")
#|
#| _MP_SQL = _insert_sql("match_player", MATCH_PLAYER)
#| _KE_SQL = _insert_sql("kill_event", KILL_EVENT)
#| _VS_SQL = _insert_sql("vehicle_session", VEHICLE_SESSION)
#|
#| def _delete_match_rows(conn: sqlite3.Connection, match_id: str) -> None:
#|     for table in ("match_player", "kill_event", "vehicle_session"):
#|         conn.execute(f"DELETE FROM {table} WHERE match_id = ?", (match_id,))
#|
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
#|                 (match_id,) + tuple(r.get(n) for n, _ in MATCH_PLAYER)
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
#|
#| def delete_match(conn: sqlite3.Connection, match_id: str) -> None:
#|     """Drop a match and the saved accumulator (an abandoned empty lobby:"""
#|     with conn:
#|         _delete_match_rows(conn, match_id)
#|         conn.execute("DELETE FROM match WHERE match_id = ?", (match_id,))
#|         conn.execute("DELETE FROM mirror_state")
#|
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
#|
#| import hashlib
#| import logging
#| import time
#| from datetime import datetime, timedelta, timezone
#| from pathlib import Path
#| from typing import Any, Callable
#|
#| from agent import local_db
#|
#| try:
#|     from replay_format import match_tag
#| except ImportError:  # pragma: no cover -- replay_format ships with the loader
#|     def match_tag(match_id):
#|         return ""
#|
#| logger = logging.getLogger("squad_replay")
#|
#| PREMATCH_MAX_WAIT_S = 600.0   # central's REPLAY_PREMATCH_MAX_WAIT_S
#| FLUSH_INTERVAL_S = 60.0
#|
#| _PRE_MATCH = ("Staging", "WaitingToStart")
#| _POST_MATCH = ("WaitingPostMatch", "LeavingMap", "EndMatch")
#|
#| def _is_skipped_map(map_name: str) -> bool:
#|     return "Jensen" in map_name or map_name == "Jensen's Training Range"
#|
#| def _iso(ts: float) -> str:
#|     return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
#|
#| class LocalMirror:
#|     """Feeds snapshots into player-stats.sqlite (see module docstring)."""
#|
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
#|
#|     # -- public ----------------------------------------------------------
#|
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
#|
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
#|
#|     # -- internals -------------------------------------------------------
#|
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
#|
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
#|
#|     def _observe(self, snap: dict[str, Any]) -> None:
#|         if not self._resume_checked:
#|             self._resume()
#|         gi = snap.get("gameInfo") or {}
#|         state = gi.get("matchState") or ""
#|         map_name = gi.get("mapName") or ""
#|         skipped = _is_skipped_map(map_name)
#|         pre = state in _PRE_MATCH
#|         now = self._clock()
#|
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
#|
#|         if self._acc is None and (state == "InProgress" or pre) and not skipped:
#|             self._open(gi, pre, now)
#|
#|         if self._acc is None:
#|             return
#|         self._acc.update(snap)
#|         if close_after:
#|             self._finish()
#|         elif now - self._last_flush >= self._flush_interval_s:
#|             self._flush(complete=False)
#|
#|     def _open(self, gi: dict[str, Any], pre: bool, now: float) -> None:
#|         self._acc = self._ms.MatchAccumulator()
#|         self._started_ts = now
#|         self._match_id = match_tag(gi.get("matchId")) or hashlib.sha1(
#|             f"{_iso(now)}|{gi.get('mapName') or ''}".encode("utf-8")).hexdigest()[:8]
#|         self._pre_since = now if pre else None
#|         self._last_flush = now
#|
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
#|
#|     def _finish(self) -> None:
#|         self._flush(complete=True)
#|         if complete_id := self._match_id:
#|             logger.info("local stats mirror: match %s recorded", complete_id)
#|         self._clear()
#|
#|     def _clear(self) -> None:
#|         self._acc = None
#|         self._match_id = None
#|         self._started_ts = None
#|         self._pre_since = None
#| ===== module: agent.memory_backend =====
#| """agent/memory_backend.py — Linux process-memory backend (pymem-compatible)."""
#| from __future__ import annotations
#|
#| import ctypes
#| import ctypes.util
#| import logging
#| import os
#| from pathlib import Path
#|
#| logger = logging.getLogger("squad_agent.backend.linux")
#|
#| class MemoryReadError(Exception):
#|     """Raised on any read failure: unmapped address, dead process,"""
#|
#| # pymem-shaped exception module so ``pymem.exception.MemoryReadError``
#| class _exception_module:  # noqa: N801 — naming mirrors pymem.exception
#|     MemoryReadError = MemoryReadError
#|
#| exception = _exception_module()
#|
#| # ---------------------------------------------------------------------------
#| _libc_path = ctypes.util.find_library("c") or "libc.so.6"
#| _libc = ctypes.CDLL(_libc_path, use_errno=True)
#|
#| class _IoVec(ctypes.Structure):
#|     _fields_ = (
#|         ("iov_base", ctypes.c_void_p),
#|         ("iov_len",  ctypes.c_size_t),
#|     )
#|
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
#|
#| # ---------------------------------------------------------------------------
#|
#| def _normalize_image(image: str | None) -> str:
#|     """Strip a legacy ``.exe`` suffix so callers can pass either spelling."""
#|     if not image:
#|         return "SquadGameServer"
#|     n = image.strip()
#|     if n.lower().endswith(".exe"):
#|         n = n[:-4]
#|     return n
#|
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
#|
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
#|
#| # ---------------------------------------------------------------------------
#| class Pymem:
#|     """Linux equivalent of ``pymem.Pymem`` — same constructor +"""
#|
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
#|
#|     def open_process_from_id(self, pid: int) -> None:
#|         pid = int(pid)
#|         # Smoke-test access — process_vm_readv on /proc/<pid>/status
#|         if not Path(f"/proc/{pid}").is_dir():
#|             raise OSError(f"no such pid: {pid}")
#|         self.process_id = pid
#|         self.process_handle = pid  # same int — used as handle by callers
#|         self.base_address = _resolve_base_address(pid, self._image)
#|
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
#|
#|     # process_vm_readv takes at most IOV_MAX (1024 on Linux) remote iovecs.
#|     _BATCH_IOVECS = 1024
#|
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
#| ===== module: agent.offset_client =====
#| """agent/offset_client.py — Agent-side offset fetch client."""
#|
#| from __future__ import annotations
#|
#| import base64
#| import json
#| import logging
#| import secrets
#| import time
#| import urllib.error
#| import urllib.request
#| from typing import Any
#|
#| from ingest import protocol as ingest_protocol
#| from ingest.crypto import CryptoError, EncryptedEnvelope
#| from ingest.offsets import open_response_envelope
#|
#| logger = logging.getLogger("SquadReplay")
#|
#| class OffsetFetchError(Exception):
#|     """Raised when the bundle cannot be fetched / verified. Non-fatal;"""
#|
#| def _b64url_decode(s: str) -> bytes:
#|     """Tolerant base64url decode — server strips padding so the client"""
#|     if not isinstance(s, str):
#|         raise ValueError("base64url field must be a string")
#|     pad = "=" * (-len(s) % 4)
#|     return base64.urlsafe_b64decode(s + pad)
#|
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
#|
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
#|
#|     try:
#|         doc = json.loads(raw)
#|         nonce = _b64url_decode(doc["nonce"])
#|         ciphertext = _b64url_decode(doc["ciphertext"])
#|     except (json.JSONDecodeError, KeyError, ValueError) as e:
#|         raise OffsetFetchError(f"bad response shape: {e}") from e
#|
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
#|
#|     try:
#|         bundle = json.loads(plaintext)
#|     except (json.JSONDecodeError, ValueError) as e:
#|         raise OffsetFetchError(f"bundle not json: {e}") from e
#|     if not isinstance(bundle, dict) or not isinstance(bundle.get("offsets"), dict):
#|         raise OffsetFetchError("bundle missing offsets dict")
#|     return bundle
#|
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
#|
#| __all__ = ["OffsetFetchError", "apply_offsets", "fetch_offsets"]
#| ===== module: agent.payload_client =====
#| """agent/payload_client.py — fetch, verify and install a code payload."""
#| from __future__ import annotations
#|
#| import json
#| import logging
#| import secrets
#| import time
#| import urllib.error
#| import urllib.request
#|
#| from agent.payload_format import PayloadError, verify
#| from agent.payload_loader import PayloadImportError, install
#| from agent.payload_trust import payload_public_key
#| from ingest import protocol as ingest_protocol
#| from ingest.crypto import CryptoError, EncryptedEnvelope
#| from ingest.offsets import open_response_envelope
#|
#| logger = logging.getLogger("SquadReplay")
#|
#| #: A payload is a few hundred KiB; refuse anything absurd before parsing.
#| MAX_RESPONSE_BYTES = 16 * 1024 * 1024
#|
#| class PayloadFetchError(Exception):
#|     """The payload could not be fetched, verified or installed."""
#|
#| def _b64url_decode(s: str) -> bytes:
#|     import base64
#|     if not isinstance(s, str):
#|         raise ValueError("base64url field must be a string")
#|     return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
#|
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
#|
#|     try:
#|         doc = json.loads(raw)
#|         env = EncryptedEnvelope(nonce=_b64url_decode(doc["nonce"]),
#|                                 ciphertext=_b64url_decode(doc["ciphertext"]))
#|     except (json.JSONDecodeError, KeyError, ValueError) as e:
#|         raise PayloadFetchError(f"bad response shape: {e}") from e
#|
#|     try:
#|         plaintext = open_response_envelope(
#|             agent_secret, env, agent_id=agent_id, seq=seq, ts=ts)
#|     except CryptoError as e:
#|         raise PayloadFetchError(f"response decrypt failed: {e}") from e
#|
#|     try:
#|         inner = json.loads(plaintext)
#|     except (json.JSONDecodeError, ValueError) as e:
#|         raise PayloadFetchError(f"payload not json: {e}") from e
#|     if not isinstance(inner, dict):
#|         raise PayloadFetchError("payload is not an object")
#|     return inner
#|
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
#|
#|     doc = fetch_payload(
#|         base_url=base_url, agent_id=agent_id, agent_secret=agent_secret,
#|         kind=kind, have_version=have_version, squad_build=squad_build,
#|         timeout=timeout,
#|     )
#|     if doc.get("uptodate"):
#|         return None
#|
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
#|
#|     version = int(doc["version"])
#|     try:
#|         install(modules, origin=f"{kind} v{version}")
#|     except PayloadImportError as e:
#|         raise PayloadFetchError(f"payload not installable: {e}") from e
#|     logger.info("payload %s v%d installed (%d module(s))",
#|                 kind, version, len(modules))
#|     return version
#|
#| __all__ = ["MAX_RESPONSE_BYTES", "PayloadFetchError", "fetch_payload",
#|            "load_payload"]
#| ===== module: agent.payload_format =====
#| """agent/payload_format.py — the signed code payload, packed and verified."""
#| from __future__ import annotations
#|
#| import base64
#| import json
#| import zlib
#| from typing import Any
#|
#| from agent.signing import SignatureError, verify_manifest
#|
#| #: What a payload can carry. Mirrors agent/capabilities.py's capabilities.
#| PAYLOAD_KINDS = ("read", "write", "voice")
#|
#| #: Wire format version of the envelope itself (not of its contents).
#| PAYLOAD_FORMAT_V = 1
#|
#| #: Decompression ceiling. The payload is signature-verified before it is
#| MAX_MODULES_BYTES = 32 * 1024 * 1024
#|
#| _SIG_FIELD = "signature"
#|
#| class PayloadError(Exception):
#|     """A payload is missing, malformed, not for us, or not trusted."""
#|
#| def _valid_module_name(name: object) -> bool:
#|     """A payload module name must be a plain dotted identifier."""
#|     if not isinstance(name, str) or not name:
#|         return False
#|     parts = name.split(".")
#|     return all(p.isidentifier() for p in parts)
#|
#| def pack(
#|     *,
#|     kind: str,
#|     version: int,
#|     modules: dict[str, str],
#|     agent_min_version: str,
#|     squad_build: str | None = None,
#| ) -> dict[str, Any]:
#|     """Build an UNSIGNED payload dict from ``{module name: source}``."""
#|     if kind not in PAYLOAD_KINDS:
#|         raise PayloadError(f"unknown payload kind: {kind!r}")
#|     if not isinstance(version, int) or isinstance(version, bool) or version < 1:
#|         raise PayloadError("version must be a positive int")
#|     if not isinstance(modules, dict) or not modules:
#|         raise PayloadError("payload carries no modules")
#|     for name, source in modules.items():
#|         if not _valid_module_name(name):
#|             raise PayloadError(f"not a module name: {name!r}")
#|         if not isinstance(source, str):
#|             raise PayloadError(f"source for {name} is not a string")
#|     blob = json.dumps(modules, sort_keys=True, ensure_ascii=False,
#|                       separators=(",", ":")).encode("utf-8")
#|     return {
#|         "v": PAYLOAD_FORMAT_V,
#|         "kind": kind,
#|         "version": version,
#|         "agent_min_version": str(agent_min_version),
#|         "squad_build": squad_build,
#|         "modules_z": base64.b64encode(zlib.compress(blob, 9)).decode("ascii"),
#|     }
#|
#| def _version_tuple(v: str) -> tuple[int, ...]:
#|     """``"0.85.1"`` -> ``(0, 85, 1)``. Unparseable parts count as 0 so a"""
#|     out = []
#|     for part in str(v).split("."):
#|         digits = "".join(c for c in part if c.isdigit())
#|         out.append(int(digits) if digits else 0)
#|     return tuple(out)
#|
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
#|
#|     got_kind = payload.get("kind")
#|     if got_kind != kind:
#|         raise PayloadError(f"payload is {got_kind!r}, asked for {kind!r}")
#|
#|     try:
#|         version = int(payload["version"])
#|     except (KeyError, TypeError, ValueError) as exc:
#|         raise PayloadError("payload has no usable version") from exc
#|     if version <= int(min_version):
#|         raise PayloadError(
#|             f"payload version {version} is not newer than {min_version}")
#|
#|     # A build-bound payload (voice: its probe address only exists in one
#|     want_build = payload.get("squad_build")
#|     if want_build is not None:
#|         if squad_build is None:
#|             raise PayloadError("payload is build-bound but our build is unknown")
#|         if str(want_build) != str(squad_build):
#|             raise PayloadError(
#|                 f"payload is for build {want_build!r}, we run {squad_build!r}")
#|
#|     need = payload.get("agent_min_version")
#|     if need and _version_tuple(agent_version) < _version_tuple(need):
#|         raise PayloadError(
#|             f"payload needs agent >= {need}, this is {agent_version}")
#|
#|     # The trust gate. Nothing below this line runs on unverified bytes.
#|     try:
#|         verify_manifest(pub, payload)
#|     except SignatureError as exc:
#|         raise PayloadError(f"signature: {exc}") from exc
#|
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
#|
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
#|
#| __all__ = [
#|     "MAX_MODULES_BYTES",
#|     "PAYLOAD_FORMAT_V",
#|     "PAYLOAD_KINDS",
#|     "PayloadError",
#|     "pack",
#|     "verify",
#| ]
#| ===== module: agent.payload_loader =====
#| """agent/payload_loader.py — import a verified payload's modules."""
#| from __future__ import annotations
#|
#| import importlib.abc
#| import importlib.machinery
#| import importlib.util
#| import logging
#| import sys
#| import types
#|
#| logger = logging.getLogger("squad_agent.payload")
#|
#| #: Module names this process installed from a payload, in install order.
#| _INSTALLED: dict[str, str] = {}
#|
#| class PayloadImportError(Exception):
#|     """A payload's modules could not be installed or imported."""
#|
#| class _PayloadFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
#|     """Serves exactly the module names a payload declared, from memory."""
#|
#|     def __init__(self, sources: dict[str, str], origin: str):
#|         self._sources = dict(sources)
#|         self._origin = origin
#|
#|     # -- MetaPathFinder --------------------------------------------------
#|     def find_spec(self, fullname, path=None, target=None):
#|         if fullname not in self._sources:
#|             return None
#|         spec = importlib.machinery.ModuleSpec(
#|             fullname, self, origin=f"<squadreplay payload {self._origin}>")
#|         spec.has_location = False
#|         return spec
#|
#|     # -- Loader ----------------------------------------------------------
#|     def create_module(self, spec):
#|         return None          # default module object
#|
#|     def exec_module(self, module: types.ModuleType) -> None:
#|         name = module.__name__
#|         source = self._sources[name]
#|         # Compile first: a syntax error then surfaces before any of the
#|         code = compile(source, module.__spec__.origin, "exec")
#|         exec(code, module.__dict__)
#|
#|     def names(self) -> tuple[str, ...]:
#|         return tuple(sorted(self._sources))
#|
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
#|
#|     finder = _PayloadFinder(modules, origin)
#|     sys.meta_path.insert(0, finder)
#|     for name in modules:
#|         _INSTALLED[name] = origin
#|     logger.info("payload %s: %d module(s) available (%s)",
#|                 origin, len(modules), ", ".join(finder.names()))
#|     return finder.names()
#|
#| def installed() -> dict[str, str]:
#|     """``{module name: origin}`` for everything a payload installed."""
#|     return dict(_INSTALLED)
#|
#| __all__ = ["PayloadImportError", "install", "installed"]
#| ===== module: agent.payload_trust =====
#| """agent/payload_trust.py — the public key payloads are verified against."""
#| from __future__ import annotations
#|
#| #: Base64 of the raw 32-byte Ed25519 public key.
#| EMBEDDED_PAYLOAD_PUBKEY_B64: str = "wz/e9lMcF40/+TCFR75g4Up6sC+f4gDthy7vQrA1VWg="
#|
#| def payload_public_key():
#|     """The baked trust anchor, or ``None`` when this build has none."""
#|     if not EMBEDDED_PAYLOAD_PUBKEY_B64:
#|         return None
#|     from agent.signing import load_public_key_from_b64
#|     return load_public_key_from_b64(EMBEDDED_PAYLOAD_PUBKEY_B64)
#|
#| __all__ = ["EMBEDDED_PAYLOAD_PUBKEY_B64", "payload_public_key"]
#| ===== module: agent.secret_store =====
#| """agent/secret_store.py — Cross-platform secret storage for the agent."""
#|
#| from __future__ import annotations
#|
#| import logging
#| import os
#| from pathlib import Path
#|
#| logger = logging.getLogger("SquadReplay")
#|
#| _SYSTEMD_CREDS_PREFIX = "systemd-creds:"
#|
#| class SecretStoreError(Exception):
#|     """Raised when an explicitly-protected value fails to decrypt."""
#|
#| def load_secret_from_env_value(value: str) -> str:
#|     """Return the plaintext hex string from whatever shape the env"""
#|     if not value:
#|         return ""
#|
#|     stripped = value.strip()
#|
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
#|
#|     # --- Plain hex ------------------------------------------------
#|     return stripped
#|
#| def protect_to_storage_string(plaintext: str) -> str:
#|     """Return the at-rest representation of ``plaintext`` for this host."""
#|     return plaintext
#|
#| def protection_available() -> bool:
#|     """True when the host supports at-rest encryption beyond"""
#|     return bool(os.environ.get("CREDENTIALS_DIRECTORY"))
#|
#| __all__ = [
#|     "SecretStoreError",
#|     "load_secret_from_env_value",
#|     "protect_to_storage_string",
#|     "protection_available",
#| ]
#| ===== module: agent.signing =====
#| """agent/signing.py — trust anchor for binary auto-update."""
#|
#| from __future__ import annotations
#|
#| import base64
#| import json
#| from pathlib import Path
#|
#| from cryptography.exceptions import InvalidSignature
#| from cryptography.hazmat.primitives.asymmetric.ed25519 import (
#|     Ed25519PrivateKey, Ed25519PublicKey,
#| )
#| from cryptography.hazmat.primitives import serialization
#|
#| class SignatureError(Exception):
#|     """Raised when a manifest signature is missing, malformed, or"""
#|
#| def generate_keypair(out_dir: Path) -> tuple[Path, Path]:
#|     """Create a brand-new Ed25519 keypair. Writes two files:"""
#|     out_dir.mkdir(parents=True, exist_ok=True)
#|     priv = Ed25519PrivateKey.generate()
#|     priv_pem = priv.private_bytes(
#|         encoding=serialization.Encoding.PEM,
#|         format=serialization.PrivateFormat.PKCS8,
#|         encryption_algorithm=serialization.NoEncryption(),
#|     )
#|     pub = priv.public_key()
#|     pub_pem = pub.public_bytes(
#|         encoding=serialization.Encoding.PEM,
#|         format=serialization.PublicFormat.SubjectPublicKeyInfo,
#|     )
#|     priv_path = out_dir / "signing_key.pem"
#|     pub_path = out_dir / "signing_pub.pem"
#|     priv_path.write_bytes(priv_pem)
#|     pub_path.write_bytes(pub_pem)
#|     # Also write a compact b64 form of the raw 32-byte public key for
#|     raw_pub = pub.public_bytes(
#|         encoding=serialization.Encoding.Raw,
#|         format=serialization.PublicFormat.Raw,
#|     )
#|     (out_dir / "signing_pub.b64").write_text(
#|         base64.b64encode(raw_pub).decode("ascii") + "\n",
#|         encoding="utf-8",
#|     )
#|     return priv_path, pub_path
#|
#| def load_private_key(path: Path) -> Ed25519PrivateKey:
#|     pem = path.read_bytes()
#|     key = serialization.load_pem_private_key(pem, password=None)
#|     if not isinstance(key, Ed25519PrivateKey):
#|         raise ValueError(f"{path} is not an Ed25519 private key")
#|     return key
#|
#| def load_public_key_from_b64(b64_raw: str) -> Ed25519PublicKey:
#|     """Public key embedded in the agent is stored as base64-encoded raw"""
#|     raw = base64.b64decode(b64_raw)
#|     return Ed25519PublicKey.from_public_bytes(raw)
#|
#| def sign_manifest(priv: Ed25519PrivateKey, manifest: dict) -> str:
#|     """Sign the CANONICAL JSON of ``manifest`` (excluding any existing"""
#|     if not isinstance(manifest, dict):
#|         raise ValueError("manifest must be a dict")
#|     body = {k: v for k, v in manifest.items() if k != "signature"}
#|     canonical = json.dumps(
#|         body, sort_keys=True, ensure_ascii=False, separators=(",", ":")
#|     ).encode("utf-8")
#|     sig = priv.sign(canonical)
#|     return base64.b64encode(sig).decode("ascii")
#|
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
#|
#| __all__ = [
#|     "SignatureError",
#|     "generate_keypair",
#|     "load_private_key",
#|     "load_public_key_from_b64",
#|     "sign_manifest",
#|     "verify_manifest",
#| ]
#| ===== module: agent.updater =====
#| """agent/updater.py — fetch, verify, self-replace."""
#|
#| from __future__ import annotations
#|
#| import base64
#| import hashlib
#| import json
#| import logging
#| import os
#| import shutil
#| import subprocess
#| import sys
#| import tempfile
#| import time
#| import urllib.error
#| import urllib.parse
#| import urllib.request
#| from pathlib import Path
#| from typing import Any
#|
#| from agent.signing import SignatureError, load_public_key_from_b64, verify_manifest
#|
#| logger = logging.getLogger("SquadReplay")
#|
#| # -----------------------------------------------------------------------
#| _EMBEDDED_PUBLIC_KEY_B64 = "icsYlNSqhAir5GeHxnuou/czdXc9qnChGSBXBlyexiU="
#|
#| # Reported by the agent and compared against the manifest. Bump this on
#| AGENT_VERSION = "0.85.3"
#|
#| # Where packaged agents push snapshots + fetch manifests / offsets.
#| _BAKED_PUSH_URL = "https://squadreplay.com"
#|
#| # How often the background updater checks. 5 min is the production
#| CHECK_INTERVAL_SECONDS = 5 * 60   # 5 min — matches CLAUDE.md "auto-update propagation" note
#|
#| # Where we persist the last-seen version number (downgrade guard) and
#| def _is_packaged() -> bool:
#|     # A downloaded single-file variant (agent/_runtime.py) is as "installed
#|     from agent import _runtime
#|     if _runtime.is_bundle():
#|         return True
#|     if getattr(sys, "frozen", False):
#|         return True
#|     main_mod = sys.modules.get("__main__")
#|     if main_mod is not None and hasattr(main_mod, "__compiled__"):
#|         return True
#|     # Nuitka also stamps ``__compiled__`` on this very module when the
#|     if "__compiled__" in globals():
#|         return True
#|     # Last-resort sniff: a Nuitka-onefile run always has the kernel-
#|     exe_name = os.path.basename(sys.executable or "").lower()
#|     if exe_name.startswith("squadreplay"):
#|         return True
#|     return False
#|
#| def _kernel_truth_exe_path() -> Path | None:
#|     """Return the absolute path of the running binary as reported by the"""
#|     try:
#|         target = os.readlink("/proc/self/exe")
#|         if target and Path(target).is_file():
#|             return Path(target).resolve()
#|     except OSError:
#|         pass
#|     return None
#|
#| def _install_root() -> Path:
#|     """Where ``.new`` should land + where the swap helper should put the"""
#|     # A single-file variant lives wherever it was put; that is its root.
#|     from agent import _runtime
#|     _bundle = _runtime.bundle_path()
#|     if _bundle is not None:
#|         return _bundle.resolve().parent
#|
#|     # Step 0 — Nuitka onefile: deploy dir is in the environment.
#|     onefile_dir = os.environ.get("NUITKA_ONEFILE_DIRECTORY")
#|     if onefile_dir:
#|         p = Path(onefile_dir)
#|         if p.is_dir():
#|             return p
#|
#|     kernel = _kernel_truth_exe_path()
#|     if kernel is not None:
#|         # Filter dev runs: ``/usr/bin/python3`` etc. Source-level run
#|         name = kernel.name.lower()
#|         if name.startswith("squadreplay"):
#|             return kernel.parent
#|     if _is_packaged():
#|         exe = Path(sys.executable)
#|         if exe.is_file():
#|             return exe.parent
#|     return Path.cwd()
#|
#| _MAX_BINARY_BYTES = 200 * 1024 * 1024  # 200 MB cap — agent binaries are ~30 MB
#|
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
#|
#| class UpdateError(Exception):
#|     """Generic update failure. The caller logs and continues — never"""
#|
#| # -----------------------------------------------------------------------
#|
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
#|
#| def is_newer(candidate: str, current: str) -> bool:
#|     return _parse_version(candidate) > _parse_version(current)
#|
#| # -----------------------------------------------------------------------
#|
#| def _platform_tag() -> str:
#|     """Map sys.platform to the manifest routing token the central"""
#|     from agent import _runtime
#|     if _runtime.is_bundle():
#|         from agent import capabilities
#|         from ingest.variants import bundle_platform
#|         return bundle_platform(capabilities.variant_name())
#|     return "linux"
#|
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
#|
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
#|
#| # -----------------------------------------------------------------------
#|
#| def _current_exe_name() -> str:
#|     """Resolve the running binary's on-disk filename (``SquadReplay``)."""
#|     from agent import _runtime
#|     _bundle = _runtime.bundle_path()
#|     if _bundle is not None:
#|         return _bundle.name
#|     if getattr(sys, "frozen", False):
#|         name = Path(sys.executable).name
#|         if name:
#|             return name
#|     return "SquadReplay"
#|
#| def _write_new_binary(new_bytes: bytes) -> Path:
#|     root = _install_root()
#|     stem = Path(_current_exe_name()).stem
#|     new_path = root / f"{stem}.new"
#|     new_path.write_bytes(new_bytes)
#|     return new_path
#|
#| def _spawn_launcher(new_path: Path) -> None:
#|     """Spawn the swap helper. It follows the same dance: wait ~2 s for"""
#|     _spawn_launcher_posix(new_path)
#|
#| def _build_posix_swap_script(*, bak: str, current_exe: str, new_path: str,
#|                              unit_hint: str, supervised: bool,
#|                              interpreter: str | None = None) -> str:
#|     """Generate the body of the POSIX self-update swap helper."""
#|     swap_head = (
#|         "#!/usr/bin/env bash\n"
#|         "# squad_agent self-update helper — autogenerated\n"
#|         "set -e\n"
#|         "sleep 2\n"
#|         f'if [ -f "{bak}" ]; then rm -f "{bak}"; fi\n'
#|         f'if [ -f "{current_exe}" ]; then mv -f "{current_exe}" "{bak}"; fi\n'
#|         f'mv -f "{new_path}" "{current_exe}"\n'
#|         f'chmod +x "{current_exe}"\n'
#|     )
#|     swap_caps = (
#|         "# Best-effort file-capability restore (see docstring above).\n"
#|         "# Not fatal — a failure here (expected when the agent runs as a\n"
#|         "# non-root service user) must not abort the binary swap. Logged\n"
#|         "# as a WARNING instead of silently dropped so it's visible to\n"
#|         "# an operator if ptrace_scope is ever reset.\n"
#|         "if command -v setcap >/dev/null 2>&1; then\n"
#|         f'    if ! setcap cap_sys_ptrace,cap_dac_read_search+eip "{current_exe}" '
#|         "2>/tmp/squad_agent_setcap_err.$$; then\n"
#|         '        echo "WARNING: setcap failed after self-update '
#|         "(likely running as non-root service user — this is expected "
#|         "and non-fatal). If kernel.yama.ptrace_scope is ever reset to 1, "
#|         "run \\`sudo setcap cap_sys_ptrace,cap_dac_read_search+eip "
#|         f'{current_exe}\\` manually or re-run \\`sudo ./SquadReplay --install\\`. '
#|         'Detail: $(cat /tmp/squad_agent_setcap_err.$$ 2>/dev/null)" >&2\n'
#|         "    fi\n"
#|         "    rm -f /tmp/squad_agent_setcap_err.$$\n"
#|         "fi\n"
#|         "\n"
#|     )
#|     swap = swap_head + ("" if interpreter else swap_caps)
#|     if interpreter:
#|         run = f'"{interpreter}" "{current_exe}"'
#|     else:
#|         run = f'"{current_exe}"'
#|     if supervised:
#|         relaunch = (
#|             "# Supervised: an external restart-loop wrapper relaunches us.\n"
#|             "# Do NOT relaunch here — a second instance would race the\n"
#|             "# wrapper's reader for PTRACE_ATTACH on the game process.\n"
#|             ": # no relaunch\n"
#|         )
#|     else:
#|         relaunch = (
#|             "# Prefer systemd if we can identify the unit. Falls through to a\n"
#|             "# bare exec when systemd isn't running this binary.\n"
#|             f'unit="{unit_hint}"\n'
#|             'if [ -z "$unit" ] && command -v systemctl >/dev/null 2>&1; then\n'
#|             "    for candidate in squad-replay-agent squad-replay squadreplay; do\n"
#|             '        if systemctl is-active --quiet "$candidate" 2>/dev/null; then\n'
#|             '            unit="$candidate"\n'
#|             "            break\n"
#|             "        fi\n"
#|             "    done\n"
#|             "fi\n"
#|             'if [ -n "$unit" ]; then\n'
#|             f'    systemctl restart "$unit" || {run} &\n'
#|             "else\n"
#|             f'    nohup {run} >/dev/null 2>&1 &\n'
#|             "fi\n"
#|         )
#|     return swap + relaunch + '\n# Self-delete.\nrm -f "$0"\n'
#|
#| def _spawn_launcher_posix(new_path: Path) -> None:
#|     """Writes a `.swap.sh` script next to the binary, marks it executable, and"""
#|     root = _install_root()
#|     exe_name = _current_exe_name()
#|     stem = Path(exe_name).stem
#|     current_exe = root / exe_name
#|     bak = root / f"{stem}.bak"
#|
#|     # Try to identify the systemd unit owning our PID. systemctl with
#|     unit_hint = os.environ.get("SQUAD_AGENT_SYSTEMD_UNIT", "")
#|     supervised = bool(os.environ.get("SQUAD_AGENT_SUPERVISED"))
#|
#|     helper = tempfile.NamedTemporaryFile(
#|         mode="w", encoding="utf-8", delete=False,
#|         dir=str(root), suffix=".swap.sh",
#|     )
#|     from agent import _runtime
#|     script = _build_posix_swap_script(
#|         bak=str(bak), current_exe=str(current_exe), new_path=str(new_path),
#|         unit_hint=unit_hint, supervised=supervised,
#|         interpreter=_runtime.interpreter() if _runtime.is_bundle() else None,
#|     )
#|     helper.write(script)
#|     helper.flush()
#|     helper.close()
#|     try:
#|         os.chmod(helper.name, 0o755)
#|         # Mayıs 2026 fix — systemd kills the entire service cgroup on
#|         running_under_systemd = bool(os.environ.get("INVOCATION_ID"))
#|         can_use_systemd_run = (
#|             shutil.which("systemd-run") is not None
#|             and running_under_systemd
#|             and os.geteuid() == 0
#|         )
#|         helper_cmd: list[str]
#|         if can_use_systemd_run:
#|             helper_cmd = [
#|                 "systemd-run", "--no-block", "--quiet", "--collect",
#|                 "--unit", f"squad-replay-swap-{os.getpid()}.service",
#|                 "--description", "squad-replay self-update binary swap",
#|                 "/bin/bash", helper.name,
#|             ]
#|         else:
#|             helper_cmd = ["/bin/bash", helper.name]
#|         subprocess.Popen(
#|             helper_cmd,
#|             close_fds=True,
#|             start_new_session=True,
#|             stdin=subprocess.DEVNULL,
#|             stdout=subprocess.DEVNULL,
#|             stderr=subprocess.DEVNULL,
#|         )
#|     except (OSError, subprocess.SubprocessError) as exc:
#|         raise UpdateError(f"helper spawn failed: {exc}") from exc
#|
#| # -----------------------------------------------------------------------
#|
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
#|
#|         pub = load_public_key_from_b64(_EMBEDDED_PUBLIC_KEY_B64)
#|         logger.info("updater: checking for updates (current=%s)", current_version)
#|         manifest = _fetch_manifest(base_url)
#|         try:
#|             verify_manifest(pub, manifest)
#|         except SignatureError as exc:
#|             raise UpdateError(f"manifest signature invalid: {exc}") from exc
#|
#|         remote_version = str(manifest.get("version") or "")
#|         if not remote_version:
#|             raise UpdateError("manifest missing version")
#|
#|         binary_url = manifest.get("binary_url")
#|         sha256 = manifest.get("sha256")
#|         if not isinstance(binary_url, str) or not isinstance(sha256, str):
#|             raise UpdateError("manifest missing binary_url or sha256")
#|         remote_sha_lc = sha256.lower()
#|
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
#|
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
#|
#|         logger.info("updater: applying update %s", remote_version)
#|         new_bytes = _download_binary(binary_url, sha256)
#|         new_path = _write_new_binary(new_bytes)
#|
#|         try:
#|             seen_path.write_text(remote_version + "\n", encoding="utf-8")
#|         except OSError as exc:
#|             logger.warning("updater: could not persist version lock: %s", exc)
#|
#|         _spawn_launcher(new_path)
#|         logger.info("updater: restarting to apply %s", remote_version)
#|         return True
#|     except UpdateError as exc:
#|         logger.warning("updater: %s", exc)
#|         return False
#|     except Exception as exc:  # pragma: no cover  # defensive catch-all
#|         logger.warning("updater: unexpected failure: %s", exc)
#|         return False
#|
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
#|
#| __all__ = [
#|     "AGENT_VERSION",
#|     "CHECK_INTERVAL_SECONDS",
#|     "UpdateError",
#|     "check_and_apply",
#|     "is_newer",
#|     "run_background",
#| ]
#| ===== package: ingest =====
#| """ingest/__init__.py — Ingest subsystem."""
#|
#| from __future__ import annotations
#|
#| __all__ = ["crypto", "protocol", "store", "registry"]
#| ===== module: ingest.crypto =====
#| """ingest/crypto.py — Authenticated encryption helpers for agent → central-server ingest."""
#|
#| from __future__ import annotations
#|
#| import os
#| from dataclasses import dataclass
#| from functools import lru_cache
#|
#| from cryptography.hazmat.primitives import hashes
#| from cryptography.hazmat.primitives.ciphers.aead import AESGCM
#| from cryptography.hazmat.primitives.kdf.hkdf import HKDF
#|
#| # Key-derivation context. Changing this value invalidates every in-flight
#| HKDF_INFO = b"squad-ingest-v1"
#|
#| # AES-GCM canonical nonce size. 12 bytes is the AES-GCM recommendation;
#| NONCE_SIZE = 12
#|
#| class CryptoError(Exception):
#|     """Raised when decryption or authentication fails. The message is"""
#|
#| @dataclass(frozen=True)
#| class EncryptedEnvelope:
#|     """Output of :func:`encrypt_snapshot` — plain bytes ready for transport."""
#|
#|     nonce: bytes
#|     ciphertext: bytes
#|
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
#|
#| def derive_key(agent_secret: bytes, *, info: bytes = HKDF_INFO) -> bytes:
#|     """Derive the AES-256 session key from a long-lived agent secret."""
#|     if not isinstance(agent_secret, (bytes, bytearray)):
#|         raise TypeError("agent_secret must be bytes")
#|     if len(agent_secret) < 16:
#|         raise ValueError("agent_secret must be at least 16 bytes")
#|     return _derive_key_cached(bytes(agent_secret), info)
#|
#| def build_aad(version: int, agent_id: str, seq: int, ts: int) -> bytes:
#|     """Construct the AAD bound to every ciphertext."""
#|     if "|" in agent_id:
#|         raise ValueError("agent_id must not contain '|'")
#|     return f"{version}|{agent_id}|{seq}|{ts}".encode("ascii")
#|
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
#|
#| def decrypt_snapshot(
#|     agent_secret: bytes,
#|     nonce: bytes,
#|     ciphertext: bytes,
#|     *,
#|     version: int,
#|     agent_id: str,
#|     seq: int,
#|     ts: int,
#| ) -> bytes:
#|     """Inverse of :func:`encrypt_snapshot`. Raises :class:`CryptoError` on"""
#|     if len(nonce) != NONCE_SIZE:
#|         raise CryptoError("bad nonce length")
#|     key = derive_key(agent_secret)
#|     aad = build_aad(version, agent_id, seq, ts)
#|     try:
#|         return AESGCM(key).decrypt(nonce, ciphertext, aad)
#|     except Exception as e:  # InvalidTag, etc. — never leak the cause.
#|         raise CryptoError("decrypt failed") from e
#|
#| VOICE_INFO = b"squad-voice-v1"
#|
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
#|
#| def decrypt_voice(
#|     agent_secret: bytes,
#|     nonce: bytes,
#|     ciphertext: bytes,
#|     *,
#|     version: int,
#|     agent_id: str,
#|     seq: int,
#|     ts: int,
#| ) -> bytes:
#|     """Inverse of :func:`encrypt_voice`. Raises :class:`CryptoError` on any"""
#|     if len(nonce) != NONCE_SIZE:
#|         raise CryptoError("bad nonce length")
#|     key = derive_key(agent_secret, info=VOICE_INFO)
#|     aad = build_aad(version, agent_id, seq, ts)
#|     try:
#|         return AESGCM(key).decrypt(nonce, ciphertext, aad)
#|     except Exception as e:  # InvalidTag, etc. — never leak the cause.
#|         raise CryptoError("decrypt failed") from e
#|
#| def generate_agent_secret() -> bytes:
#|     """Produce a fresh 32-byte agent secret. Intended for provisioning a"""
#|     return os.urandom(32)
#| ===== module: ingest.offsets =====
#| """ingest/offsets.py — central → agent."""
#|
#| from __future__ import annotations
#|
#| import json
#| import logging
#| import threading
#| from pathlib import Path
#| from typing import Any
#|
#| import os
#|
#| from cryptography.hazmat.primitives.ciphers.aead import AESGCM
#|
#| from .crypto import NONCE_SIZE, CryptoError, EncryptedEnvelope, derive_key
#|
#| logger = logging.getLogger("squad_map_server.ingest.offsets")
#|
#| RESP_AAD_TAG = b"resp"  # prefix distinguishes responses from ingest
#| MAX_REQUEST_BYTES = 64 * 1024  # bundle request is tiny JSON; cap tight
#|
#| class OffsetBundleError(Exception):
#|     """Raised when the bundle file is missing or malformed."""
#|
#| class OffsetBundle:
#|     """Read-only view of the offsets.json bundle."""
#|
#|     def __init__(self, path: Path) -> None:
#|         self._path = path
#|         self._lock = threading.RLock()
#|         self._bundle_id: str | None = None
#|         self._offsets: dict[str, Any] = {}
#|
#|     def load(self) -> None:
#|         """Read the JSON file. Raises :class:`OffsetBundleError` on"""
#|         try:
#|             raw = self._path.read_text(encoding="utf-8-sig")
#|         except FileNotFoundError as e:
#|             raise OffsetBundleError(f"offsets file not found: {self._path}") from e
#|         try:
#|             doc = json.loads(raw)
#|         except (json.JSONDecodeError, ValueError) as e:
#|             raise OffsetBundleError(f"offsets not valid json: {e}") from e
#|         if not isinstance(doc, dict):
#|             raise OffsetBundleError("offsets file must be a json object")
#|         bundle_id = doc.get("bundleId")
#|         offsets = doc.get("offsets")
#|         if not isinstance(bundle_id, str) or not bundle_id:
#|             raise OffsetBundleError("missing bundleId string")
#|         if not isinstance(offsets, dict):
#|             raise OffsetBundleError("offsets must be an object")
#|         with self._lock:
#|             self._bundle_id = bundle_id
#|             self._offsets = offsets
#|
#|     @property
#|     def loaded(self) -> bool:
#|         return self._bundle_id is not None
#|
#|     def build_response_payload(self) -> bytes:
#|         """UTF-8 JSON plaintext that gets encrypted for an agent."""
#|         with self._lock:
#|             if self._bundle_id is None:
#|                 raise OffsetBundleError("bundle not loaded")
#|             body = {
#|                 "bundleId": self._bundle_id,
#|                 "offsets": dict(self._offsets),
#|             }
#|         return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
#|
#| def _build_response_aad(version: int, agent_id: str, seq: int, ts: int) -> bytes:
#|     """Construct the AAD bound to an offset response ciphertext."""
#|     if "|" in agent_id:
#|         raise ValueError("agent_id must not contain '|'")
#|     label = RESP_AAD_TAG.decode("ascii")
#|     return f"{label}|{version}|{agent_id}|{seq}|{ts}".encode("ascii")
#|
#| def build_response_envelope(
#|     agent_secret: bytes,
#|     *,
#|     agent_id: str,
#|     seq: int,
#|     ts: int,
#|     plaintext: bytes,
#|     version: int = 1,
#|     nonce: bytes | None = None,
#| ) -> EncryptedEnvelope:
#|     """Seal the bundle for one agent."""
#|     key = derive_key(agent_secret)
#|     aad = _build_response_aad(version, agent_id, seq, ts)
#|     if nonce is None:
#|         nonce = os.urandom(NONCE_SIZE)
#|     elif len(nonce) != NONCE_SIZE:
#|         raise ValueError(f"nonce must be exactly {NONCE_SIZE} bytes")
#|     ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
#|     return EncryptedEnvelope(nonce=nonce, ciphertext=ciphertext)
#|
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
#|
#| __all__ = [
#|     "MAX_REQUEST_BYTES",
#|     "OffsetBundle",
#|     "OffsetBundleError",
#|     "build_response_envelope",
#|     "open_response_envelope",
#| ]
#| ===== module: ingest.protocol =====
#| """ingest/protocol.py — Wire-format for agent → central ingest."""
#|
#| from __future__ import annotations
#|
#| import base64
#| import binascii
#| import gzip
#| import json
#| import time
#| from dataclasses import dataclass
#| from typing import Any
#|
#| from .crypto import (
#|     NONCE_SIZE,
#|     CryptoError,
#|     decrypt_snapshot,
#|     decrypt_voice,
#|     encrypt_snapshot,
#|     encrypt_voice,
#| )
#|
#| PROTOCOL_VERSION = 1
#|
#| # Maximum allowed clock skew between agent and central server, seconds.
#| MAX_TS_SKEW_SECONDS = 120
#|
#| # Hard ceiling on compressed payload size. Memory snapshots are ~150 KB
#| MAX_CIPHERTEXT_BYTES = 5 * 1024 * 1024
#|
#| class ProtocolError(Exception):
#|     """Raised when an incoming envelope fails structural/freshness checks."""
#|
#| @dataclass(frozen=True)
#| class IngestEnvelope:
#|     """Parsed, validated wire envelope. Ciphertext is **not** yet"""
#|
#|     version: int
#|     agent_id: str
#|     seq: int
#|     ts: int
#|     nonce: bytes
#|     ciphertext: bytes
#|
#| def _b64url_encode(data: bytes) -> str:
#|     return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
#|
#| def _b64url_decode(s: str) -> bytes:
#|     # Restore padding — urlsafe_b64decode is strict about it.
#|     pad = "=" * (-len(s) % 4)
#|     try:
#|         return base64.urlsafe_b64decode(s + pad)
#|     except (binascii.Error, ValueError) as e:
#|         raise ProtocolError("bad base64") from e
#|
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
#|
#| def parse_envelope(raw: bytes, *, now: int | None = None) -> IngestEnvelope:
#|     """Validate a wire envelope's structure and freshness. Does NOT"""
#|     if len(raw) > MAX_CIPHERTEXT_BYTES * 2:
#|         # Rough upper bound — ciphertext is base64 so ~4/3 inflated; with
#|         raise ProtocolError("envelope too large")
#|     try:
#|         doc = json.loads(raw)
#|     except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
#|         raise ProtocolError("not valid json") from e
#|     if not isinstance(doc, dict):
#|         raise ProtocolError("envelope must be an object")
#|
#|     try:
#|         version = int(doc["v"])
#|         agent_id = doc["agent_id"]
#|         seq = int(doc["seq"])
#|         ts = int(doc["ts"])
#|         nonce_b64 = doc["nonce"]
#|         ciphertext_b64 = doc["ciphertext"]
#|     except (KeyError, TypeError, ValueError) as e:
#|         raise ProtocolError("missing or malformed field") from e
#|
#|     # NOTE: some in-flight agent builds from before hardware-fingerprint
#|
#|     if version != PROTOCOL_VERSION:
#|         raise ProtocolError(f"unsupported protocol version {version}")
#|     if not isinstance(agent_id, str) or not agent_id or "|" in agent_id:
#|         raise ProtocolError("bad agent_id")
#|     if seq < 0:
#|         raise ProtocolError("seq must be non-negative")
#|     if not isinstance(nonce_b64, str) or not isinstance(ciphertext_b64, str):
#|         raise ProtocolError("nonce/ciphertext must be base64 strings")
#|
#|     nonce = _b64url_decode(nonce_b64)
#|     ciphertext = _b64url_decode(ciphertext_b64)
#|     if len(nonce) != NONCE_SIZE:
#|         raise ProtocolError("wrong nonce size")
#|     if not ciphertext:
#|         raise ProtocolError("empty ciphertext")
#|     if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
#|         raise ProtocolError("ciphertext too large")
#|
#|     now = now if now is not None else int(time.time())
#|     if abs(now - ts) > MAX_TS_SKEW_SECONDS:
#|         raise ProtocolError("timestamp outside freshness window")
#|
#|     return IngestEnvelope(
#|         version=version,
#|         agent_id=agent_id,
#|         seq=seq,
#|         ts=ts,
#|         nonce=nonce,
#|         ciphertext=ciphertext,
#|     )
#|
#| def decrypt_envelope(envelope: IngestEnvelope, agent_secret: bytes) -> dict[str, Any]:
#|     """Unseal an envelope and return the parsed snapshot JSON."""
#|     plaintext = decrypt_snapshot(
#|         agent_secret,
#|         envelope.nonce,
#|         envelope.ciphertext,
#|         version=envelope.version,
#|         agent_id=envelope.agent_id,
#|         seq=envelope.seq,
#|         ts=envelope.ts,
#|     )
#|     try:
#|         snapshot_bytes = gzip.decompress(plaintext)
#|     except (OSError, EOFError) as e:
#|         raise ProtocolError("bad gzip") from e
#|     try:
#|         snapshot = json.loads(snapshot_bytes)
#|     except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
#|         raise ProtocolError("plaintext not json") from e
#|     if not isinstance(snapshot, dict):
#|         raise ProtocolError("snapshot must be a json object")
#|     return snapshot
#|
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
#|
#| def decrypt_voice_envelope(envelope: IngestEnvelope, agent_secret: bytes) -> dict[str, Any]:
#|     """Unseal a voice envelope and return the batch dict. Raises"""
#|     plaintext = decrypt_voice(
#|         agent_secret, envelope.nonce, envelope.ciphertext,
#|         version=envelope.version, agent_id=envelope.agent_id,
#|         seq=envelope.seq, ts=envelope.ts,
#|     )
#|     try:
#|         batch_bytes = gzip.decompress(plaintext)
#|     except (OSError, EOFError) as e:
#|         raise ProtocolError("bad gzip") from e
#|     try:
#|         batch = json.loads(batch_bytes)
#|     except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
#|         raise ProtocolError("plaintext not json") from e
#|     if not isinstance(batch, dict) or not isinstance(batch.get("utterances"), list):
#|         raise ProtocolError("voice batch must be an object with utterances[]")
#|     return batch
#|
#| __all__ = [
#|     "CryptoError",
#|     "IngestEnvelope",
#|     "MAX_CIPHERTEXT_BYTES",
#|     "MAX_TS_SKEW_SECONDS",
#|     "PROTOCOL_VERSION",
#|     "ProtocolError",
#|     "decrypt_envelope",
#|     "decrypt_voice_envelope",
#|     "encode_envelope",
#|     "encode_voice_envelope",
#|     "parse_envelope",
#| ]
#| ===== module: ingest.variants =====
#| """ingest/variants.py -- the agent variants and the update channels they use."""
#| from __future__ import annotations
#|
#| #: Every variant the project ships, in the order they are listed everywhere.
#| VARIANTS = ("read", "read-write", "read-voice", "read-write-voice")
#|
#| #: The compiled-binary channel (unchanged since before variants existed).
#| BINARY_PLATFORM = "linux"
#|
#| _BUNDLE_PREFIX = "linux-py-"
#|
#| def bundle_platform(variant: str) -> str:
#|     """``read`` -> ``linux-py-read``. Raises for a name that is not a variant."""
#|     if variant not in VARIANTS:
#|         raise ValueError(f"not an agent variant: {variant!r}")
#|     return _BUNDLE_PREFIX + variant
#|
#| #: Every platform token central will route to a manifest.
#| PLATFORM_TAGS = (BINARY_PLATFORM,) + tuple(bundle_platform(v) for v in VARIANTS)
#|
#| def variant_of_platform(tag: str) -> str | None:
#|     """``linux-py-read-write`` -> ``read-write``; ``linux`` / junk -> None."""
#|     if isinstance(tag, str) and tag.startswith(_BUNDLE_PREFIX):
#|         v = tag[len(_BUNDLE_PREFIX):]
#|         if v in VARIANTS:
#|             return v
#|     return None
#|
#| def is_platform_tag(tag: object) -> bool:
#|     """Whether central may use ``tag`` to pick a manifest file. An allowlist,"""
#|     return isinstance(tag, str) and tag in PLATFORM_TAGS
#|
#| def artifact_name(variant: str, version: str) -> str:
#|     """The published file for a variant at a version."""
#|     if variant not in VARIANTS:
#|         raise ValueError(f"not an agent variant: {variant!r}")
#|     return f"squadreplay-agent-{variant}-{version}.py"
#|
#| __all__ = ["BINARY_PLATFORM", "PLATFORM_TAGS", "VARIANTS", "artifact_name",
#|            "bundle_platform", "is_platform_tag", "variant_of_platform"]
#| ===== module: live_data_mmap =====
#| """live_data_mmap.py — Shared-memory live data channel."""
#|
#| from __future__ import annotations
#|
#| import mmap
#| import os
#| import struct
#| import time
#| from pathlib import Path
#|
#| MAGIC = b"SQLD"            # "Squad Live Data"
#| VERSION = 1
#| HEADER_SIZE = 64           # magic(4) + version(4) + seq(8) + length(8) + 40 reserved
#| _HEADER_FMT = "<4sIQQ40x"  # little-endian: bytes, uint32, uint64, uint64, 40 pad
#| assert struct.calcsize(_HEADER_FMT) == HEADER_SIZE
#|
#| DEFAULT_CAPACITY = 8 * 1024 * 1024  # 8 MiB body (header excluded)
#| _MAX_READER_RETRIES = 8             # seqlock retry budget
#| _BUSY_SPIN_SLEEP = 0.001            # 1 ms between retries
#|
#| class BodyTooLargeError(Exception):
#|     """Raised when the snapshot doesn't fit in the allocated mmap."""
#|
#| class CorruptMmapError(Exception):
#|     """Raised when the header doesn't look like ours (wrong magic/version)."""
#|
#| def _default_path(json_path: Path) -> Path:
#|     """Sidecar path: ``squad_live_data.json`` -> ``squad_live_data.mmap``."""
#|     return json_path.with_suffix(".mmap")
#|
#| class LiveDataWriter:
#|     """Single-writer side. Owns the file and grows it to full capacity."""
#|
#|     def __init__(self, path: Path, capacity: int = DEFAULT_CAPACITY) -> None:
#|         self.path = Path(path)
#|         self.capacity = capacity
#|         self._total = HEADER_SIZE + capacity
#|
#|         # Ensure the backing file exists and is at least total size. We fill
#|         fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
#|         try:
#|             st = os.fstat(fd)
#|             if st.st_size < self._total:
#|                 os.ftruncate(fd, self._total)
#|             self._mm = mmap.mmap(fd, self._total, access=mmap.ACCESS_WRITE)
#|         finally:
#|             os.close(fd)
#|
#|         self._write_initial_header_if_needed()
#|
#|     def _write_initial_header_if_needed(self) -> None:
#|         """If the magic is missing or wrong, initialize the header."""
#|         self._mm.seek(0)
#|         magic = self._mm.read(4)
#|         if magic != MAGIC:
#|             self._mm.seek(0)
#|             self._mm.write(struct.pack(_HEADER_FMT, MAGIC, VERSION, 0, 0))
#|             self._mm.flush()
#|
#|     def _read_seq(self) -> int:
#|         self._mm.seek(8)  # skip magic(4) + version(4)
#|         return struct.unpack("<Q", self._mm[8:16])[0]
#|
#|     def _write_seq(self, seq: int) -> None:
#|         self._mm[8:16] = struct.pack("<Q", seq)
#|
#|     def _write_length(self, length: int) -> None:
#|         self._mm[16:24] = struct.pack("<Q", length)
#|
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
#|
#|     def close(self) -> None:
#|         try:
#|             self._mm.flush()
#|         finally:
#|             self._mm.close()
#|
#|     def __enter__(self) -> "LiveDataWriter":
#|         return self
#|
#|     def __exit__(self, *_: object) -> None:
#|         self.close()
#|
#| class LiveDataReader:
#|     """Read-only side. Safe for concurrent readers via seqlock."""
#|
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
#|
#|         # Remember the inode we actually mapped so a later on-disk swap
#|         self._ino = st.st_ino
#|         self._dev = st.st_dev
#|
#|         magic = bytes(self._mm[0:4])
#|         version = struct.unpack("<I", self._mm[4:8])[0]
#|         if magic != MAGIC:
#|             raise CorruptMmapError(f"bad magic: {magic!r}")
#|         if version != VERSION:
#|             raise CorruptMmapError(f"unsupported version: {version}")
#|
#|     def is_replaced(self) -> bool:
#|         """True if ``self.path`` now points at a different inode than the"""
#|         try:
#|             st = os.stat(self.path)
#|         except OSError:
#|             return True
#|         return st.st_ino != self._ino or st.st_dev != self._dev
#|
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
#|
#|     def close(self) -> None:
#|         self._mm.close()
#|
#|     def __enter__(self) -> "LiveDataReader":
#|         return self
#|
#|     def __exit__(self, *_: object) -> None:
#|         self.close()
#| ===== module: proc_utils =====
#| """proc_utils.py — Process utilities for single-instance enforcement."""
#|
#| from __future__ import annotations
#|
#| import logging
#| import os
#| import signal
#|
#| from agent._platform import (
#|     IS_LINUX,
#|     find_pid as _plat_find_pid,
#|     list_processes_by_name as _plat_list_processes,
#| )
#|
#| logger = logging.getLogger(__name__)
#|
#| def kill_previous_instances(script_marker: str, timeout: float = 5.0) -> int:
#|     """Kill any other Python/Nuitka processes whose command line contains"""
#|     if not IS_LINUX:
#|         return 0
#|
#|     current_pid = os.getpid()
#|
#|     # Image names to sweep. The installed interpreter could be
#|     image_candidates = ("python", "python3", "python3.10",
#|                         "python3.11", "python3.12", "python3.13",
#|                         "SquadReplay")
#|
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
#|
#|     if not victims:
#|         return 0
#|
#|     killed = 0
#|     for pid in victims:
#|         if _terminate_pid(pid, timeout):
#|             logger.warning(
#|                 "Killed orphan %s (pid=%s) from previous run",
#|                 script_marker, pid,
#|             )
#|             killed += 1
#|
#|     return killed
#|
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
#|
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
#| ===== module: replay_format =====
#| """replay_format.py — SquadReplay encrypted replay file format (``.sqrx``)."""
#|
#| from __future__ import annotations
#|
#| import gzip
#| import os
#| import re
#| import struct
#| import time
#| from pathlib import Path
#| from typing import Iterator
#|
#| from cryptography.exceptions import InvalidTag
#| from cryptography.hazmat.primitives.ciphers.aead import AESGCM
#|
#| # Producers tag the filename with the first 8 chars of ``gameInfo.matchId``
#| MATCH_TAG_LEN = 8
#|
#| # Resume gate. A match-tagged file older than this is considered
#| RESUME_MAX_AGE_SECONDS = 4 * 3600
#|
#| _MATCH_TAG_RE = re.compile(r"^[0-9a-fA-F]+$")
#|
#| def match_tag(match_id: str | None) -> str:
#|     """Return the canonical 8-char filename tag for a match id."""
#|     if not match_id:
#|         return ""
#|     cleaned = match_id.strip().replace("-", "")
#|     if not cleaned or not _MATCH_TAG_RE.match(cleaned):
#|         return ""
#|     return cleaned[:MATCH_TAG_LEN].lower()
#|
#| def find_resumable_replay(
#|     replay_dir: Path | str,
#|     match_tag_value: str,
#|     *,
#|     max_age_seconds: float = RESUME_MAX_AGE_SECONDS,
#| ) -> Path | None:
#|     """Locate an in-progress replay file for ``match_tag_value``."""
#|     if not match_tag_value:
#|         return None
#|     d = Path(replay_dir)
#|     if not d.is_dir():
#|         return None
#|     tag = match_tag_value.lower()
#|     candidates: list[Path] = []
#|     for ext in (".sqrx", ".ndjson"):
#|         candidates.extend(d.glob(f"*_{tag}{ext}"))
#|     if not candidates:
#|         return None
#|     now = time.time()
#|     fresh = []
#|     for p in candidates:
#|         try:
#|             age = now - p.stat().st_mtime
#|         except OSError:
#|             continue
#|         if age <= max_age_seconds:
#|             fresh.append((p.stat().st_mtime, p))
#|     if not fresh:
#|         return None
#|     fresh.sort(key=lambda t: t[0], reverse=True)
#|     return fresh[0][1]
#|
#| MAGIC = b"SQRX"
#| VERSION = 0x01
#| _HEADER_SIZE = 24
#| _FILE_ID_SIZE = 16
#| _NONCE_SIZE = 12
#| _KEY_SIZE = 32  # AES-256
#|
#| class ReplayFormatError(Exception):
#|     """Raised when a ``.sqrx`` file is truncated, tampered, or sealed"""
#|
#| def _parse_master_key(hex_or_bytes: str | bytes) -> bytes:
#|     if isinstance(hex_or_bytes, bytes):
#|         if len(hex_or_bytes) != _KEY_SIZE:
#|             raise ValueError(f"replay key must be {_KEY_SIZE} bytes, got {len(hex_or_bytes)}")
#|         return hex_or_bytes
#|     hex_str = hex_or_bytes.strip()
#|     if len(hex_str) != _KEY_SIZE * 2:
#|         raise ValueError(
#|             f"replay key must be {_KEY_SIZE*2}-char hex, got {len(hex_str)}")
#|     try:
#|         return bytes.fromhex(hex_str)
#|     except ValueError as exc:
#|         raise ValueError(f"replay key is not valid hex: {exc}") from exc
#|
#| def _aad(file_id: bytes, record_idx: int) -> bytes:
#|     return f"sqrx|{file_id.hex()}|{record_idx}".encode("ascii")
#|
#| class ReplayWriter:
#|     """Append-only writer. Call :meth:`write` per snapshot then"""
#|
#|     def __init__(self, path: Path | str, master_key: str | bytes):
#|         self.path = Path(path)
#|         self._key = _parse_master_key(master_key)
#|         self._gcm = AESGCM(self._key)
#|         self._file_id = os.urandom(_FILE_ID_SIZE)
#|         self._record_idx = 0
#|         self._f = open(self.path, "wb")
#|         header = MAGIC + bytes([VERSION, 0, 0, 0]) + self._file_id
#|         assert len(header) == _HEADER_SIZE
#|         self._f.write(header)
#|         self._f.flush()
#|
#|     @classmethod
#|     def open_for_append(cls, path: Path | str, master_key: str | bytes) -> "ReplayWriter":
#|         """Resume writing into an existing ``.sqrx`` file."""
#|         path = Path(path)
#|         key_bytes = _parse_master_key(master_key)
#|         with open(path, "rb") as f:
#|             header = f.read(_HEADER_SIZE)
#|             if len(header) != _HEADER_SIZE:
#|                 raise ReplayFormatError("header truncated — cannot resume")
#|             if header[:4] != MAGIC:
#|                 raise ReplayFormatError(f"bad magic: {header[:4]!r}")
#|             if header[4] != VERSION:
#|                 raise ReplayFormatError(f"unsupported version: {header[4]}")
#|             file_id = header[8:24]
#|             # Walk length prefixes to count complete records. Stop at the
#|             record_count = 0
#|             complete_offset = _HEADER_SIZE
#|             while True:
#|                 prefix = f.read(4)
#|                 if len(prefix) < 4:
#|                     break
#|                 length = struct.unpack("<I", prefix)[0]
#|                 # Sanity: per-record body has nonce(12) + ct(>=16 tag).
#|                 if length < (_NONCE_SIZE + 16) or length > (64 * 1024 * 1024):
#|                     break
#|                 body = f.read(length)
#|                 if len(body) != length:
#|                     break
#|                 record_count += 1
#|                 complete_offset = f.tell()
#|
#|         self = cls.__new__(cls)
#|         self.path = path
#|         self._key = key_bytes
#|         self._gcm = AESGCM(self._key)
#|         self._file_id = file_id
#|         self._record_idx = record_count
#|         # r+b allows seek + truncate on the existing file. Truncating to
#|         self._f = open(path, "r+b")
#|         self._f.seek(complete_offset)
#|         self._f.truncate(complete_offset)
#|         return self
#|
#|     def write(self, snapshot_bytes: bytes) -> None:
#|         """Compress + encrypt + append one record. ``snapshot_bytes``"""
#|         if self._f is None:
#|             raise ReplayFormatError("writer closed")
#|         compressed = gzip.compress(snapshot_bytes, compresslevel=5)
#|         nonce = os.urandom(_NONCE_SIZE)
#|         ct = self._gcm.encrypt(nonce, compressed, _aad(self._file_id, self._record_idx))
#|         body = nonce + ct
#|         self._f.write(struct.pack("<I", len(body)) + body)
#|         self._f.flush()
#|         self._record_idx += 1
#|
#|     def close(self) -> None:
#|         if self._f is not None:
#|             self._f.close()
#|             self._f = None
#|
#|     def __enter__(self) -> "ReplayWriter":
#|         return self
#|
#|     def __exit__(self, *exc_info) -> None:
#|         self.close()
#|
#| class ReplayReader:
#|     """Iterator over a ``.sqrx`` file. Yields raw snapshot bytes in"""
#|
#|     def __init__(self, path: Path | str, master_key: str | bytes):
#|         self.path = Path(path)
#|         self._key = _parse_master_key(master_key)
#|         self._gcm = AESGCM(self._key)
#|         self._f = open(self.path, "rb")
#|         header = self._f.read(_HEADER_SIZE)
#|         if len(header) != _HEADER_SIZE:
#|             raise ReplayFormatError("header truncated")
#|         if header[:4] != MAGIC:
#|             raise ReplayFormatError(f"bad magic: {header[:4]!r}")
#|         if header[4] != VERSION:
#|             raise ReplayFormatError(f"unsupported version: {header[4]}")
#|         self._file_id = header[8:24]
#|         self._record_idx = 0
#|
#|     def __iter__(self) -> Iterator[bytes]:
#|         return self
#|
#|     def __next__(self) -> bytes:
#|         prefix = self._f.read(4)
#|         if not prefix:
#|             raise StopIteration
#|         if len(prefix) != 4:
#|             raise ReplayFormatError("record length field truncated")
#|         length = struct.unpack("<I", prefix)[0]
#|         body = self._f.read(length)
#|         if len(body) != length:
#|             raise ReplayFormatError(
#|                 f"record body truncated at idx {self._record_idx}: "
#|                 f"wanted {length}, got {len(body)}")
#|         nonce = body[:_NONCE_SIZE]
#|         ct = body[_NONCE_SIZE:]
#|         try:
#|             compressed = self._gcm.decrypt(
#|                 nonce, ct, _aad(self._file_id, self._record_idx))
#|         except InvalidTag as exc:
#|             raise ReplayFormatError(
#|                 f"decrypt failed at record {self._record_idx} — wrong key "
#|                 f"or tampered file") from exc
#|         try:
#|             snapshot = gzip.decompress(compressed)
#|         except (OSError, EOFError, gzip.BadGzipFile) as exc:
#|             raise ReplayFormatError(
#|                 f"gzip decode failed at record {self._record_idx}: {exc}") from exc
#|         self._record_idx += 1
#|         return snapshot
#|
#|     def close(self) -> None:
#|         if self._f is not None:
#|             self._f.close()
#|             self._f = None
#|
#|     def __enter__(self) -> "ReplayReader":
#|         return self
#|
#|     def __exit__(self, *exc_info) -> None:
#|         self.close()
#|
#| def count_sqrx_records(path: Path | str) -> int:
#|     """Fast frame count for a ``.sqrx`` file. Walks only the per-record"""
#|     try:
#|         with open(path, "rb") as f:
#|             header = f.read(_HEADER_SIZE)
#|             if len(header) != _HEADER_SIZE or header[:4] != MAGIC:
#|                 return 0
#|             n = 0
#|             while True:
#|                 prefix = f.read(4)
#|                 if not prefix:
#|                     return n
#|                 if len(prefix) != 4:
#|                     return n
#|                 length = struct.unpack("<I", prefix)[0]
#|                 f.seek(length, 1)
#|                 n += 1
#|     except (OSError, FileNotFoundError):
#|         return 0
#|
#| def is_sqrx_file(path: Path | str) -> bool:
#|     """Cheap magic-byte check so endpoints can route to the right"""
#|     try:
#|         with open(path, "rb") as f:
#|             head = f.read(4)
#|     except (OSError, FileNotFoundError):
#|         return False
#|     return head == MAGIC
#|
#| __all__ = [
#|     "MAGIC",
#|     "VERSION",
#|     "ReplayFormatError",
#|     "ReplayReader",
#|     "ReplayWriter",
#|     "is_sqrx_file",
#| ]
#| ===== module: squad_memory_reader =====
#| """squad_memory_reader.py -- the SquadReplay agent's entry point (the loader)."""
#|
#| import os
#| import sys
#| import json
#| import time
#| import struct
#| import argparse
#| import logging
#| import gc
#| import logging.handlers
#| from datetime import datetime, timezone
#| from pathlib import Path
#| import math
#|
#| # 'WaitingToStart' is a real Squad state (server loaded the map,
#| _VALID_MATCH_STATES = {
#|     'Staging', 'InProgress', 'WaitingPostMatch', 'EndMatch',
#|     'LeavingMap', 'WaitingToStart', 'None', 'Unknown', '',
#| }
#|
#| # Pre-match lobby states that legitimately precede 'InProgress' in
#| _PRE_MATCH_STATES = frozenset({'Staging', 'WaitingToStart'})
#|
#| def _is_pre_match_state(match_state: str) -> bool:
#|     """True for the pre-'InProgress' lobby states that should still open"""
#|     return match_state in _PRE_MATCH_STATES
#|
#| def _is_garbage_gamestate(match_state: str, elapsed_raw, map_name: str = '') -> bool:
#|     """True when the GameState pointer looks stale and this tick's"""
#|     try:
#|         elapsed = float(elapsed_raw or 0)
#|     except (TypeError, ValueError):
#|         elapsed = -1.0
#|     if match_state not in _VALID_MATCH_STATES:
#|         return True
#|     if elapsed < 0:
#|         return True
#|     if elapsed > 86400 and 'Jensen' not in (map_name or ''):
#|         return True
#|     return False
#|
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
#|
#| _auto_load_env_files()
#|
#| try:
#|     # ctypes-backed `pymem` reimplementation that uses
#|     from agent import memory_backend as pymem
#| except ImportError:
#|     # Generic, redacted failure text — internal module names must never
#|     sys.stderr.write(
#|         "ERROR: a required runtime component failed to initialize.\n"
#|         "Make sure the project root is on PYTHONPATH.\n"
#|     )
#|     sys.exit(1)
#|
#| from proc_utils import kill_previous_instances, find_process_pid
#| from live_data_mmap import LiveDataWriter, BodyTooLargeError, DEFAULT_CAPACITY
#|
#| # The Squad-specific reader. In a checkout it sits next to this file; a
#| try:
#|     import sq_reader as _sq_reader
#|     from sq_reader import (  # noqa: F401  (re-exported for tools and tests)
#|         SquadMemoryReader, _FIELD_MAP, projectile_kind,
#|         _NESTED_FIELD_MAP, _NESTED_PATH_FIELD_MAP, _ARRAY_ELEMENT_FIELD_MAP,
#|         _ARRAY_ELEMENT_NESTED_FIELD_MAP, _BOOL_FIELD_MAP,
#|         _mine_cache_entry_valid, _is_garbage_map_name, _is_cacheable_fname,
#|         _fired_since_last_tick, _decode_fstring_buffer,
#|     )
#| except ModuleNotFoundError as _exc:
#|     if _exc.name != "sq_reader":
#|         raise
#|     _sq_reader = None
#|     SquadMemoryReader = None  # type: ignore[assignment,misc]
#|
#| # Optional — only used when --push is enabled.
#| try:
#|     from ingest import protocol as ingest_protocol
#| except ImportError:  # pragma: no cover — ingest package always present locally
#|     ingest_protocol = None  # type: ignore[assignment]
#|
#| import binascii
#|
#| sys.stdout.reconfigure(encoding='utf-8', errors='replace')
#|
#| logger = logging.getLogger("SquadReplay")
#|
#| # ---------------------------------------------------------------------------
#|
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
#|
#| def _public_exc_name(exc_type) -> str:
#|     """Map an internal exception class to its operator-facing name."""
#|     try:
#|         return _PUBLIC_EXC_NAMES.get(exc_type.__name__, "SquadReplayError")
#|     except AttributeError:
#|         return "SquadReplayError"
#|
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
#|
#| # Install the hook + zero traceback frames at module load time so any
#| sys.excepthook = _redacted_excepthook
#| sys.tracebacklimit = 0
#|
#| class IngestPusher:
#|     """Encrypts and POSTs snapshots to a central ingest endpoint."""
#|
#|     _CONTENT_TYPE = "application/json"
#|     _TIMEOUT_SEC = 10.0
#|
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
#|
#|         self._seq_path = seq_state_path
#|         self._seq = self._load_seq()
#|         self._last_error_repr: str | None = None
#|         # Threaded in from SquadMemoryReader._offset_health by the caller
#|         self._offset_health: dict = {'healed': 0, 'warnings': 0}
#|
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
#|
#|     @property
#|     def secret(self) -> bytes:
#|         """Read-only access to the decoded shared secret. Used by the"""
#|         return self._secret
#|
#|     def _load_seq(self) -> int:
#|         try:
#|             raw = self._seq_path.read_text(encoding="utf-8").strip()
#|             value = int(raw)
#|             if value < 0:
#|                 raise ValueError("negative seq")
#|             return value
#|         except (FileNotFoundError, ValueError, OSError):
#|             return 0
#|
#|     def _save_seq(self) -> None:
#|         try:
#|             self._seq_path.parent.mkdir(parents=True, exist_ok=True)
#|             self._seq_path.write_text(str(self._seq), encoding="utf-8")
#|         except OSError as e:
#|             # Non-fatal — on next restart we'd resend from a lower seq
#|             logger.warning("cannot persist push seq to %s: %s", self._seq_path, e)
#|
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
#|
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
#|
#|     def _log_error(self, reason: str) -> None:
#|         # Rate-limit identical errors so a disconnected central server
#|         if self._last_error_repr == reason:
#|             return
#|         self._last_error_repr = reason
#|         logger.warning("push: %s (url=%s, seq=%d)", reason, self._url, self._seq)
#|
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
#|
#| # ----------------------------------------------------------------------
#|
#| def _agent_dir() -> Path:
#|     """Directory next to the running binary / source."""
#|     onefile_dir = os.environ.get("NUITKA_ONEFILE_DIRECTORY")
#|     if onefile_dir:
#|         p = Path(onefile_dir)
#|         if p.is_dir():
#|             return p
#|     return Path(__file__).resolve().parent
#|
#| DEFAULT_CONFIG_PATH = _agent_dir() / "squad_replay_config.json"
#| # Older deploys shipped with this name; auto-fallback at load time keeps
#| LEGACY_CONFIG_PATH = _agent_dir() / "squad_reader_config.json"
#|
#| def sanitize_nan(obj):
#|     """Replace NaN/Inf floats with None recursively."""
#|     if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
#|         return None
#|     if isinstance(obj, dict):
#|         return {k: sanitize_nan(v) for k, v in obj.items()}
#|     if isinstance(obj, list):
#|         return [sanitize_nan(v) for v in obj]
#|     return obj
#|
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
#|
#| def _bind_reader_host() -> None:
#|     """Give the Squad reader the loader-side pieces it cannot find itself"""
#|     if _sq_reader is not None:
#|         _sq_reader.bind_host(load_mod_configs=_load_mod_reader_configs)
#|
#| _bind_reader_host()
#|
#| def _ensure_squad_reader(*, base_url: str, agent_id: str,
#|                          agent_secret: bytes) -> None:
#|     """Make sure the Squad-specific reader is loaded."""
#|     global _sq_reader, SquadMemoryReader
#|     if SquadMemoryReader is not None:
#|         return
#|     import importlib
#|     try:
#|         from agent.payload_client import PayloadFetchError, load_payload
#|         from agent.updater import AGENT_VERSION
#|     except ImportError as exc:
#|         logger.error("payload client unavailable (%s); this file cannot load "
#|                      "the reader without it.", exc)
#|         sys.exit(2)
#|     try:
#|         load_payload(base_url=base_url, agent_id=agent_id,
#|                      agent_secret=agent_secret, kind="read",
#|                      agent_version=AGENT_VERSION, have_version=0)
#|     except PayloadFetchError as exc:
#|         logger.error("could not load the reader from central (%s). Check the "
#|                      "--push URL, agent id and secret, and that this agent is "
#|                      "up to date.", exc)
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
#|     _sq_reader = importlib.import_module("sq_reader")
#|     SquadMemoryReader = _sq_reader.SquadMemoryReader
#|     _bind_reader_host()
#|     logger.info("Squad reader loaded from central")
#|
#| def _load_mod_admin_cam_patterns() -> tuple[str, ...]:
#|     """Convenience wrapper — returns admin_cam_patterns tuple from all enabled mods."""
#|     return tuple(_load_mod_reader_configs()['admin_cam_patterns'])
#|
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
#|
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
#|
#|     if cfg is None:
#|         logger.info("No service config found (looked at %s) — using defaults",
#|                     [str(c) for c in candidates])
#|         return defaults
#|     for k, v in defaults.items():
#|         cfg.setdefault(k, v)
#|     return cfg
#|
#| def _is_pid_alive(pid: int) -> bool:
#|     """Return True if pid currently maps to a running process."""
#|     try:
#|         from agent._platform import is_pid_alive as _platform_alive
#|         return _platform_alive(pid)
#|     except ImportError:
#|         # Defensive fallback — should never trigger in a normal agent
#|         return bool(pid and pid > 0)
#|
#| def _match_cmdline_for(config: dict) -> str | None:
#|     """The cmdline substring that selects the right SquadGameServer instance."""
#|     if config.get("match_cmdline"):
#|         return config["match_cmdline"]
#|     port = config.get("port")
#|     if port:
#|         return f"Port={int(port)}"
#|     return None
#|
#| def discover_squad_pid(config: dict) -> int | None:
#|     """One-shot discovery. Returns PID or None."""
#|     return find_process_pid(
#|         image_name=config.get("process_name") or "SquadGameServer",
#|         executable_path=config.get("executable_path"),
#|         match_cmdline=_match_cmdline_for(config),
#|     )
#|
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
#|
#| def _close_reader_pm(reader) -> None:
#|     """No-op placeholder for the reconnect path."""
#|
#| # GObjects/GNames anchors this agent itself found (or confirmed), keyed by
#| ANCHOR_CACHE_PATH = _agent_dir() / "anchor_cache.json"
#| _ANCHOR_CACHE_MAX_ENTRIES = 8
#| # Module-level, not per-reader: every attach builds a fresh reader, and a
#| _last_anchor_rediscovery = 0.0
#|
#| def _game_binary_identity(pid: int) -> str | None:
#|     """Identity of the executable behind ``pid`` (None if unreadable)."""
#|     try:
#|         st = os.stat(f"/proc/{pid}/exe")
#|     except OSError:
#|         return None
#|     return f"{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}"
#|
#| def _load_anchor_cache(identity: str, path: Path | None = None) -> tuple[int, int] | None:
#|     try:
#|         entry = json.loads((path or ANCHOR_CACHE_PATH).read_text()).get(identity)
#|         return int(entry["gobjects"]), int(entry["gnames"])
#|     except (OSError, ValueError, TypeError, KeyError, AttributeError):
#|         return None
#|
#| def _save_anchor_cache(identity: str, gobjects: int, gnames: int,
#|                        path: Path | None = None) -> None:
#|     path = path or ANCHOR_CACHE_PATH
#|     try:
#|         data = json.loads(path.read_text())
#|         if not isinstance(data, dict):
#|             data = {}
#|     except (OSError, ValueError):
#|         data = {}
#|     data.pop(identity, None)
#|     data[identity] = {"gobjects": gobjects, "gnames": gnames,
#|                       "savedAt": int(time.time())}
#|     for old in list(data)[:-_ANCHOR_CACHE_MAX_ENTRIES]:
#|         del data[old]
#|     tmp = path.with_name(path.name + ".tmp")
#|     try:
#|         tmp.write_text(json.dumps(data, indent=1))
#|         os.replace(tmp, path)
#|     except OSError as e:
#|         logger.warning("Could not save anchor cache: %s", e)
#|
#| def build_reader(pid: int) -> 'SquadMemoryReader':
#|     """Attach to ``pid`` and make sure the GObjects/GNames anchors fit."""
#|     global _last_anchor_rediscovery
#|     logger.info("Connecting to service...")
#|     identity = _game_binary_identity(pid)
#|     cached = _load_anchor_cache(identity) if identity else None
#|     current = (SquadMemoryReader.GOBJECTS_OFFSET, SquadMemoryReader.GNAMES_OFFSET)
#|     if cached and cached != current:
#|         SquadMemoryReader.GOBJECTS_OFFSET, SquadMemoryReader.GNAMES_OFFSET = cached
#|         logger.info("Using GObjects/GNames anchors cached for this game build")
#|     r = SquadMemoryReader(pid=pid)
#|
#|     threshold = SquadMemoryReader._ANCHOR_HEALED_THRESHOLD
#|     healed = (r._offset_health or {}).get('healed', 0)
#|     now = time.time()
#|     if (healed < threshold and now - _last_anchor_rediscovery
#|             >= SquadMemoryReader._ANCHOR_REDISCOVERY_COOLDOWN_SECONDS):
#|         _last_anchor_rediscovery = now
#|         logger.warning(
#|             "Self-heal healed=%d on attach -- attempting automatic "
#|             "GObjects/GNames anchor rediscovery", healed)
#|         if r._rediscover_gobjects_gnames():
#|             # Class-level anchors were just updated -- rebuild cleanly so
#|             r = SquadMemoryReader(pid=pid)
#|             healed = (r._offset_health or {}).get('healed', 0)
#|             logger.warning("Anchor rediscovery applied: reader rebuilt, "
#|                            "healed=%d", healed)
#|
#|     pair = (SquadMemoryReader.GOBJECTS_OFFSET, SquadMemoryReader.GNAMES_OFFSET)
#|     if identity and healed >= threshold and pair != cached:
#|         _save_anchor_cache(identity, *pair)
#|     # Keep PID in the happy-path log because ops want it for
#|     logger.info("Connected.")
#|     logger.debug("base: %s", hex(r.base))
#|     return r
#|
#| def _position_sample_ts(base_elapsed: float, slice_s: float, sample_index: int) -> float:
#|     """ts for the (sample_index+1)-th 4Hz position-only sample within a"""
#|     return base_elapsed + slice_s * (sample_index + 1)
#|
#| def _decompress_view_pitch_byte(raw_byte: int) -> float:
#|     """Decode the pawn's compressed view-pitch byte (a uint8) into degrees,"""
#|     degrees = raw_byte * 360.0 / 255.0
#|     if degrees > 180.0:
#|         degrees -= 360.0
#|     return degrees
#|
#| def _extract_argv_value(flag: str) -> str | None:
#|     """Read ``--flag value`` or ``--flag=value`` from ``sys.argv`` without"""
#|     argv = sys.argv
#|     for i, a in enumerate(argv):
#|         if a == flag and i + 1 < len(argv):
#|             return argv[i + 1].strip() or None
#|         if a.startswith(flag + "="):
#|             return a.split("=", 1)[1].strip() or None
#|     return None
#|
#| def _agent_variant_name() -> str:
#|     try:
#|         from agent.capabilities import variant_name
#|     except ImportError:
#|         return "unknown"
#|     return variant_name()
#|
#| def main():
#|
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
#|             )
#|         except InstallError as exc:
#|             _print_error_banner(exc)
#|             sys.exit(7)
#|         sys.exit(rc)
#|
#|     # ``--enroll-only`` signals "write .env.agent and exit". Used by the
#|     _enroll_only_requested = "--enroll-only" in sys.argv
#|     if _enroll_only_requested:
#|         # Strip it so argparse never sees it (we'd exit before argparse
#|         sys.argv = [a for a in sys.argv if a != "--enroll-only"]
#|
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
#|
#|     parser = argparse.ArgumentParser(description='SquadReplay Agent')
#|     parser.add_argument('--interval', type=int, default=None,
#|                         help='Update interval in seconds (default: 5 in '
#|                              'legacy mode, 1 in agent/--push mode for '
#|                              'tighter UI refresh)')
#|     parser.add_argument('--output', type=str, default='squad_live_data.json', help='Output JSON file')
#|     parser.add_argument('--once', action='store_true', help='Run once and exit')
#|     parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON')
#|     parser.add_argument('--replay-dir', type=str, default='replays', help='Directory for replay files')
#|     parser.add_argument('--replay-max-files', type=int, default=30,
#|                         metavar='N',
#|                         help='Keep at most N replay files per server '
#|                              '(oldest deleted first; .sqrx + .ndjson '
#|                              'both swept). Default 30 — adjust upward '
#|                              'for archival operators or pass 0 to '
#|                              'disable the cap entirely. Local-mode '
#|                              'mirror of the central --replay-max-files '
#|                              'flag, applied at fresh-file creation '
#|                              '(never on resume, never on the actively '
#|                              'recording file).')
#|     parser.add_argument('--replay-max-age-days', type=float, default=None,
#|                         metavar='DAYS',
#|                         help='Delete replay files older than DAYS. No '
#|                              'cutoff by default. Combined with '
#|                              '--replay-max-files (both rules applied).')
#|     parser.add_argument('--log-level', type=str, default='INFO',
#|                         choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
#|                         help='Logging verbosity (default: INFO)')
#|     parser.add_argument('--log-file', type=str, default=None,
#|                         help='Optional log file path (messages are also written to stdout)')
#|     parser.add_argument('--no-mmap', action='store_true',
#|                         help='Disable shared-memory sidecar (write JSON file only). '
#|                              'Use when debugging or when the reader is the only consumer.')
#|     parser.add_argument('--mmap-capacity', type=int, default=DEFAULT_CAPACITY,
#|                         help=f'Max snapshot size in bytes (default {DEFAULT_CAPACITY}). '
#|                              'Writer auto-grows on overflow.')
#|     parser.add_argument('--local-db', type=str, default='player-stats.sqlite',
#|                         metavar='PATH',
#|                         help='Local copy of every match\'s player stats (SQLite), '
#|                              'the same numbers as the central leaderboard '
#|                              '(default: player-stats.sqlite in the working '
#|                              'directory).')
#|     parser.add_argument('--no-local-db', action='store_true',
#|                         help='Do not keep the local player-stats.sqlite.')
#|     parser.add_argument('--push', type=str, default=None, metavar='URL',
#|                         help='Base URL of the central ingest server '
#|                              '(e.g. https://squadreplay.com). Each tick the '
#|                              'snapshot is AES-GCM sealed and POSTed to '
#|                              '<url>/ingest/snapshot. Requires --agent-id and '
#|                              '--secret-hex.')
#|     parser.add_argument('--agent-id', type=str, default=None,
#|                         help='Agent id registered in the central agents.json '
#|                              '(required with --push).')
#|     parser.add_argument('--secret-hex', type=str, default=None,
#|                         help='Hex-encoded shared secret for this agent '
#|                              '(required with --push). Minimum 16 bytes. '
#|                              'Alternatively read from env SQUAD_AGENT_SECRET_HEX.')
#|     parser.add_argument('--seq-state', type=str, default=None,
#|                         help='Path for persisted ingest sequence counter '
#|                              '(default <output>.push.seq). Must outlive '
#|                              'reader restarts so the central server does '
#|                              'not reject stale seqs.')
#|     # ``--install`` / ``--force-user`` / ``--deploy-dir`` are dispatched
#|     parser.add_argument('--install', action='store_true',
#|                         help='One-shot Linux self-install (sudo required). '
#|                              'Detects the running SquadGameServer, sets '
#|                              'ptrace_scope=0 via sysctl drop-in, writes '
#|                              'start.sh (own restart loop, no systemd unit), '
#|                              'applies file capabilities, and (when paired '
#|                              'with --enroll <token>) provisions the agent '
#|                              'with central. Idempotent; safe to re-run as a '
#|                              'repair step. Exits after install.')
#|     parser.add_argument('--force-user', type=str, default=None, metavar='USER',
#|                         help='Override the auto-detected Squad service user '
#|                              'during --install. Use when multiple Squad '
#|                              'instances run under different accounts on the '
#|                              'same host.')
#|     parser.add_argument('--deploy-dir', type=str, default=None, metavar='PATH',
#|                         help='Override the default deploy directory '
#|                              '(default: $HOME/BOTS/SquadReplay of the '
#|                              'detected Squad user) during --install. '
#|                              'start.sh is written here.')
#|     parser.add_argument('--enroll', type=str, default=None, metavar='TOKEN',
#|                         help='One-time enrollment token issued by central. '
#|                              'Used during --install or fresh agent boot to '
#|                              'mint an agent secret for this host. Token is '
#|                              'consumed before argparse runs; this entry '
#|                              'exists only for --help.')
#|     parser.add_argument('--pid', type=int, default=None,
#|                         help='Attach to a specific target PID instead of '
#|                              'the first one found by name. Useful when '
#|                              'multiple instances share a host; also '
#|                              'disables the orphan-reader killer so the '
#|                              'production reader is not terminated.')
#|     parser.add_argument('--no-kill-orphans', action='store_true',
#|                         help='Skip the startup orphan-reader kill. Implied '
#|                              'by --pid. Use when intentionally running more '
#|                              'than one reader instance side by side '
#|                              '(e.g. prod + test) with different --output / '
#|                              '--replay-dir paths.')
#|     parser.add_argument('--config', type=str, default=None,
#|                         help='Path to squad_replay_config.json. Controls '
#|                              'executable_path, process_name, and '
#|                              'attach_retry_seconds. Ignored when --pid is '
#|                              'set. Defaults to ./squad_replay_config.json '
#|                              'next to this script (legacy '
#|                              './squad_reader_config.json is still read as '
#|                              'a fallback).')
#|     args = parser.parse_args()
#|
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
#|
#|     # Process-start timestamp — wall-clock, captured as early in main() as
#|     control_process_start_ts = time.time()
#|
#|     # Last successful offset-bundle fetch (agent mode only — see the
#|     control_last_offset_fetch_ts: float | None = None
#|
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
#|
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
#|
#|     _configure_logging(args.log_level, args.log_file)
#|
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
#|
#|     # Ensure replay directory exists — but only in local-recording mode.
#|     replay_dir = Path(args.replay_dir)
#|     if args.push is None:
#|         replay_dir.mkdir(parents=True, exist_ok=True)
#|
#|     # Runtime offset fetch: when --push is active (agent mode), central
#|     if SquadMemoryReader is None:
#|         if pusher is None:
#|             logger.error("The Squad reader is not part of this file, and it "
#|                          "can only be fetched in agent mode (--push).")
#|             sys.exit(2)
#|         _ensure_squad_reader(base_url=args.push, agent_id=args.agent_id,
#|                              agent_secret=pusher.secret)
#|
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
#|         control_last_offset_fetch_ts = time.time()
#|         logger.info(
#|             "Configuration applied (%d entries) — service ready",
#|             len(applied),
#|         )
#|         logger.debug(
#|             "diag: 'VEH_ENGINE_ACTIVE' in applied: %s",
#|             'VEH_ENGINE_ACTIVE' in applied,
#|         )
#|
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
#|
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
#|
#|     if args.pid is not None:
#|         logger.info("Connecting to service (explicit)...")
#|         reader = build_reader(args.pid)
#|         current_pid = args.pid
#|     else:
#|         logger.info(
#|             "Auto-attach mode (retry=%ds)",
#|             reader_config.get("attach_retry_seconds", 5),
#|         )
#|         current_pid = wait_for_squad_pid(reader_config)
#|         reader = build_reader(current_pid)
#|
#|     # Shared-memory channel: readers (HTTP server) mmap this file, so every
#|     mmap_writer: LiveDataWriter | None = None
#|     mmap_capacity = args.mmap_capacity
#|     if not args.no_mmap:
#|         mmap_path = Path(args.output).with_suffix('.mmap')
#|         try:
#|             mmap_writer = LiveDataWriter(mmap_path, capacity=mmap_capacity)
#|             logger.info("Data channel ready (capacity=%d bytes)", mmap_capacity)
#|         except OSError as e:
#|             logger.warning("Data channel unavailable (%s) — using file fallback", e)
#|             mmap_writer = None
#|
#|     # Local player-stats.sqlite: every snapshot pushed below is also folded
#|     local_mirror = None
#|     if not args.no_local_db:
#|         from agent.local_mirror import LocalMirror
#|         local_mirror = LocalMirror(args.local_db, server_id=args.agent_id)
#|         import atexit
#|         atexit.register(local_mirror.close)
#|
#|     last_match_state = ''
#|     leaving_map_count = 0
#|     none_state_count = 0
#|
#|     # Lifetime re-attach counter for this process run (not reset on a
#|     control_reattach_count = 0
#|
#|     def _rebind_per_process_state(new_reader):
#|         """Called after every re-attach so per-process auxiliary state"""
#|         nonlocal control_reattach_count
#|         control_reattach_count += 1
#|
#|     # Rate-limited counters for transient memory-read failures. A MemoryReadError
#|     mem_err_count = 0
#|     mem_err_window_start = time.time()
#|     MEM_ERR_SUMMARY_INTERVAL = 3600.0  # seconds
#|
#|     # Consecutive-failure tracker for process-death detection. If the target
#|     consec_read_err = 0
#|     CONSEC_READ_ERR_RECONNECT = 3  # ~3 ticks @ interval seconds
#|
#|     # Persistent null-GameState watchdog. MemoryReadError-based reattach
#|     persistent_null_gs = 0
#|     CONSEC_NULL_GS_REATTACH = max(10, int(60 / max(args.interval, 1)))
#|     # Consecutive ingest-push failure counter — escalates log severity
#|     _push_consec_fail = 0
#|
#|     # Replay recording state
#|     replay_file = None
#|     replay_path = None
#|     replay_snap_count = 0
#|     replay_match_map = ''
#|     # Push-mode agents never open a local replay file (central records via
#|     last_started_match_id = None
#|     # Pre-match recording window (Staging/WaitingToStart) safety valve.
#|     pre_match_open_since = None
#|     REPLAY_PREMATCH_MAX_WAIT_S = 600.0  # 10 min; observed real waits are <20s on populated servers
#|     # Tick counter for periodic gc.collect() — see comment in main loop.
#|     main_loop_tick: int = 0
#|
#|     # Rules: tune the cyclic GC thresholds for the reader's allocation
#|     gc.set_threshold(70000, 100, 100)
#|
#|     # Replay encryption — if SQUAD_REPLAY_KEY is in env, prefer the
#|     _replay_key_hex = (os.environ.get('SQUAD_REPLAY_KEY') or '').strip()
#|     _replay_key: bytes | None = None
#|     if _replay_key_hex:
#|         try:
#|             _k = bytes.fromhex(_replay_key_hex)
#|             if len(_k) == 32:
#|                 _replay_key = _k
#|             else:
#|                 logger.warning("SQUAD_REPLAY_KEY must be 32 bytes, got %d; "
#|                                "replay encryption disabled", len(_k))
#|         except ValueError as exc:
#|             logger.warning("SQUAD_REPLAY_KEY invalid hex (%s); replay "
#|                            "encryption disabled", exc)
#|
#|     class _PlainNdjsonWriter:
#|         """Shim around plain-text NDJSON so it mirrors ReplayWriter's"""
#|         def __init__(self, path, append: bool = False):
#|             self._record_idx = 0
#|             if append:
#|                 # Count existing lines so callers can surface a true
#|                 try:
#|                     with open(path, 'rb') as f:
#|                         for _ in f:
#|                             self._record_idx += 1
#|                 except OSError:
#|                     self._record_idx = 0
#|             self._f = open(path, 'ab' if append else 'wb')
#|         def write(self, snap_bytes: bytes) -> None:
#|             self._f.write(snap_bytes)
#|             self._f.write(b'\n')
#|             self._f.flush()
#|             self._record_idx += 1
#|         def close(self) -> None:
#|             if self._f is not None:
#|                 self._f.close()
#|                 self._f = None
#|
#|     def start_replay(map_name: str, game_mode: str, elapsed: int, match_id: str = '') -> None:
#|         nonlocal replay_file, replay_path, replay_snap_count, replay_match_map
#|         # Clear previous-match kill feed and damage events so the first
#|         reader._damage_events.clear()
#|         reader._take_hit_state.clear()
#|         if hasattr(reader, '_kf_feed'):
#|             reader._kf_feed.clear()
#|         if hasattr(reader, '_kf_last_wounder'):
#|             reader._kf_last_wounder.clear()
#|             reader._kf_prev_deaths.clear()
#|             reader._kf_world_kill_for_eos.clear()
#|         # Push/agent mode: the central host already records the match
#|         if pusher is not None:
#|             return
#|         stop_replay()
#|         # Match-id tag in the filename lets us resume the same replay
#|         from replay_format import (
#|             match_tag as _match_tag,
#|             find_resumable_replay,
#|         )
#|         tag = _match_tag(match_id)
#|         # UTC, not naive local time — parse_filename() in db/import_match.py
#|         ts = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')
#|         safe_map = (map_name or 'Unknown').replace(' ', '_').replace('/', '_')
#|         safe_mode = (game_mode or 'Unknown').replace(' ', '_').replace('/', '_')
#|
#|         # Resume path: find an existing in-progress file for this match
#|         existing = find_resumable_replay(replay_dir, tag) if tag else None
#|         target = existing
#|         append_mode = existing is not None
#|
#|         if not append_mode:
#|             # Quota sweep: enforce the per-directory cap BEFORE opening
#|             try:
#|                 from ingest.replay_quota import enforce_quota
#|                 cap = args.replay_max_files if args.replay_max_files and args.replay_max_files > 0 else None
#|                 age_cap = args.replay_max_age_days if args.replay_max_age_days and args.replay_max_age_days > 0 else None
#|                 if cap is not None or age_cap is not None:
#|                     sweep_cap = max(0, cap - 1) if cap is not None else None
#|                     enforce_quota(
#|                         replay_dir,
#|                         max_files=sweep_cap,
#|                         max_age_days=age_cap,
#|                     )
#|             except Exception:  # pragma: no cover — never block a match
#|                 logger.exception("replay quota sweep crashed")
#|
#|             suffix = f"_{tag}" if tag else ""
#|             if _replay_key is not None:
#|                 fname = f"{ts}_{safe_map}_{safe_mode}{suffix}.sqrx"
#|             else:
#|                 fname = f"{ts}_{safe_map}_{safe_mode}{suffix}.ndjson"
#|             target = replay_dir / fname
#|
#|         # Any open() failure (disk full, perms, path too long, sqrx
#|         try:
#|             if _replay_key is not None and (target.suffix == '.sqrx' if append_mode else True):
#|                 from replay_format import ReplayWriter, ReplayFormatError
#|                 if append_mode:
#|                     try:
#|                         fh = ReplayWriter.open_for_append(target, _replay_key)
#|                     except ReplayFormatError as exc:
#|                         # Resume failed (corrupt header / wrong key) — bail
#|                         logger.warning(
#|                             "Replay resume failed for %s (%s); starting fresh file",
#|                             target, exc,
#|                         )
#|                         append_mode = False
#|                         suffix = f"_{tag}" if tag else ""
#|                         target = replay_dir / f"{ts}_{safe_map}_{safe_mode}{suffix}.sqrx"
#|                         fh = ReplayWriter(target, _replay_key)
#|                 else:
#|                     fh = ReplayWriter(target, _replay_key)
#|             else:
#|                 # Either ndjson legacy mode, or resuming an .ndjson under
#|                 fh = _PlainNdjsonWriter(target, append=append_mode)
#|         except (OSError, ValueError) as exc:
#|             logger.warning("Replay file open failed (%s): %s — disabling replay for this match", target, exc)
#|             replay_file = None
#|             replay_path = None
#|             replay_snap_count = 0
#|             replay_match_map = ''
#|             return
#|         replay_file = fh
#|         replay_path = target
#|         # Preserve the existing record count when resuming so the log
#|         if append_mode and hasattr(fh, '_record_idx'):
#|             replay_snap_count = getattr(fh, '_record_idx', 0)
#|         else:
#|             replay_snap_count = 0
#|         replay_match_map = map_name
#|         if append_mode:
#|             logger.info("Recording resumed (%d existing snapshots) -> %s", replay_snap_count, replay_path)
#|         else:
#|             logger.info("Recording started -> %s", replay_path)
#|
#|     def stop_replay() -> None:
#|         nonlocal replay_file, replay_path, replay_snap_count
#|         if replay_file:
#|             replay_file.close()
#|             logger.info("Recording stopped (%d snapshots) -> %s", replay_snap_count, replay_path)
#|             replay_file = None
#|             replay_path = None
#|             replay_snap_count = 0
#|
#|     def write_replay_snapshot(json_str: str) -> None:
#|         nonlocal replay_snap_count
#|         if replay_file:
#|             replay_file.write(json_str.encode('utf-8'))
#|             replay_snap_count += 1
#|
#|     def push_position_sample(json_str: str) -> None:
#|         """Ship one 4Hz position-only sample to central over the same"""
#|         assert pusher is not None
#|         pusher._offset_health = reader._offset_health
#|         try:
#|             pusher.push(json_str.encode('utf-8'))
#|         except Exception:
#|             logger.exception("position-sample push raised")
#|
#|     def sleep_with_position_sampling(total_sleep: float, base_elapsed: float) -> None:
#|         """Subdivide the tick's sleep into 4 slices; after each of the"""
#|         sink = push_position_sample if pusher is not None else write_replay_snapshot
#|         slice_s = total_sleep / 4
#|         for i in range(3):
#|             time.sleep(slice_s)
#|             if not replay_file and pusher is None:
#|                 continue  # recording stopped mid-wait (e.g. match ended)
#|             try:
#|                 frame = reader._sample_positions(
#|                     _position_sample_ts(base_elapsed, slice_s, i))
#|             except (pymem.exception.MemoryReadError, struct.error, OSError,
#|                     AttributeError, ValueError, TypeError):
#|                 continue
#|             if frame['p'] or frame['v']:
#|                 sink(json.dumps(
#|                     frame, ensure_ascii=False, separators=(',', ':')))
#|         time.sleep(max(0.0, total_sleep - slice_s * 3))
#|
#|     while True:
#|         try:
#|             cycle_start = time.time()
#|             data = reader.read_all()
#|             gi = data['gameInfo']
#|             match_state = gi['matchState']
#|             _elapsed_raw = gi.get('elapsedTime', 0) or 0
#|
#|             # Garbage GameState detection — see _is_garbage_gamestate()
#|             if _is_garbage_gamestate(match_state, _elapsed_raw, gi.get('mapName', '')):
#|                 logger.warning(
#|                     "Garbage GameState detected (matchState=%r, elapsed=%s) "
#|                     "— stale pointer; forcing rescan + skipping this tick.",
#|                     match_state, _elapsed_raw,
#|                 )
#|                 reader.game_state = reader._find_game_state_instance()
#|                 reader.persistent_level_ptr = None
#|                 reader.logist_collector_ptr = None
#|                 reader.combat_collector_ptr = None
#|                 reader.obj_collector_ptr = None
#|                 reader._raas_lane_instance = None
#|                 reader._raas_lane_searched = False
#|                 reader._marker_mgr_ptr = None
#|                 reader._marker_mgr_searched = False
#|                 persistent_null_gs += 1
#|                 if (persistent_null_gs >= CONSEC_NULL_GS_REATTACH
#|                         and args.pid is None):
#|                     logger.warning(
#|                         "GameState garbage for %d ticks — dropping attach "
#|                         "and re-discovering PID.",
#|                         persistent_null_gs,
#|                     )
#|                     stop_replay()
#|                     persistent_null_gs = 0
#|                     consec_read_err = 0
#|                     current_pid = wait_for_squad_pid(reader_config)
#|                     reader = build_reader(current_pid)
#|                     _rebind_per_process_state(reader)
#|                 # Don't publish this tick — snapshot is full of garbage
#|                 time.sleep(args.interval)
#|                 continue
#|
#|             # Manager remote-control poll (restart / fetch_logs). Internally
#|
#|             # Refresh game_state pointer on map transitions.
#|             if last_match_state == 'LeavingMap' and match_state != 'LeavingMap':
#|                 logger.info("Session transition detected (%s -> %s), refreshing service state...", last_match_state, match_state)
#|                 reader.game_state = reader._find_game_state_instance()
#|                 # New GameState means new PersistentLevel → invalidate cache
#|                 reader.persistent_level_ptr = None
#|                 # The stats-collector singleton gets re-allocated on
#|                 reader.logist_collector_ptr = None
#|                 reader.combat_collector_ptr = None
#|                 reader.obj_collector_ptr = None
#|                 # RAAS lane initializer: per-map singleton. Negative-cache
#|                 reader._raas_lane_instance = None
#|                 reader._raas_lane_searched = False
#|                 # Sticky placer cache: actor pointers from the previous
#|                 reader._placer_cache.clear()
#|                 # Wipe spawner ↔ vehicle bindings — a new layer has its own
#|                 reader._clear_match_vehicle_bindings()
#|                 # Wipe FName + class caches at every map boundary. The
#|                 fname_dropped = len(reader.fname_cache)
#|                 class_dropped = len(reader.class_cache)
#|                 reader.fname_cache.clear()
#|                 reader.class_cache.clear()
#|                 logger.info(
#|                     "Maintenance: %d entries cleared",
#|                     fname_dropped + class_dropped,
#|                 )
#|                 logger.info("Service refreshed.")
#|                 leaving_map_count = 0
#|                 none_state_count = 0
#|             elif match_state == 'LeavingMap':
#|                 leaving_map_count += 1
#|                 none_state_count = 0
#|                 # Re-scan on the very FIRST LeavingMap tick (count==1) AND
#|                 if leaving_map_count == 1 or leaving_map_count % 5 == 0:
#|                     logger.warning("Still in transition (%d ticks), re-checking...", leaving_map_count)
#|                     new_gs = reader._find_game_state_instance()
#|                     if new_gs and new_gs != reader.game_state:
#|                         logger.info("Session anchor changed during transition: %s -> %s",
#|                                     hex(reader.game_state) if reader.game_state else 'None',
#|                                     hex(new_gs))
#|                     reader.game_state = new_gs
#|                     # Force re-find of the supply collector singleton next tick.
#|                     reader.logist_collector_ptr = None
#|                     reader.combat_collector_ptr = None
#|                     reader.obj_collector_ptr = None
#|                     reader._raas_lane_instance = None
#|                     reader._raas_lane_searched = False
#|                     reader._marker_mgr_ptr = None
#|                     reader._marker_mgr_searched = False
#|             elif match_state in ('None', 'Unknown', '') and not gi.get('mapName'):
#|                 none_state_count += 1
#|                 leaving_map_count = 0
#|                 if none_state_count >= 5:
#|                     logger.warning("Stale state (%s, %d ticks), refreshing service state...", match_state, none_state_count)
#|                     reader.game_state = reader._find_game_state_instance()
#|                     reader.persistent_level_ptr = None
#|                     logger.info("Service refreshed.")
#|                     reader.logist_collector_ptr = None
#|                     reader.combat_collector_ptr = None
#|                     reader.obj_collector_ptr = None
#|                     reader._raas_lane_instance = None
#|                     reader._raas_lane_searched = False
#|                     reader._marker_mgr_ptr = None
#|                     reader._marker_mgr_searched = False
#|                     # Map-scoped cache clear — this branch fires when a real
#|                     reader._placer_cache.clear()
#|                     reader._clear_match_vehicle_bindings()
#|                     fname_dropped = len(reader.fname_cache)
#|                     class_dropped = len(reader.class_cache)
#|                     reader.fname_cache.clear()
#|                     reader.class_cache.clear()
#|                     logger.info(
#|                         "Maintenance: %d entries cleared (stale-state path)",
#|                         fname_dropped + class_dropped,
#|                     )
#|                     none_state_count = 0
#|                 # Persistent null-GameState → the attached process is
#|                 if not reader.game_state:
#|                     persistent_null_gs += 1
#|                 else:
#|                     persistent_null_gs = 0
#|             else:
#|                 leaving_map_count = 0
#|                 none_state_count = 0
#|                 persistent_null_gs = 0
#|
#|             # Force full reattach if GameState stayed null too long.
#|             if (persistent_null_gs >= CONSEC_NULL_GS_REATTACH
#|                     and args.pid is None):
#|                 logger.warning(
#|                     "GameState has been NULL for %d ticks (~%ds) — "
#|                     "dropping attach on PID=%s and re-discovering.",
#|                     persistent_null_gs,
#|                     persistent_null_gs * args.interval,
#|                     current_pid,
#|                 )
#|                 stop_replay()
#|                 persistent_null_gs = 0
#|                 consec_read_err = 0
#|                 current_pid = wait_for_squad_pid(reader_config)
#|                 # Stale GObjects/GNames (a Squad update) are rediscovered
#|                 reader = build_reader(current_pid)
#|                 _rebind_per_process_state(reader)
#|                 continue
#|
#|             # Replay recording logic. Lobby / training maps are filtered out
#|             map_name = gi.get('mapName', '') or ''
#|             is_skipped_map = 'Jensen' in map_name or map_name == 'Jensen\'s Training Range'
#|             # Replay write/close decisions:
#|             close_after_write = False
#|             is_pre_match_state = _is_pre_match_state(match_state)
#|             if (match_state == 'InProgress' or is_pre_match_state) and not is_skipped_map:
#|                 cur_match_id = gi.get('matchId', '') or ''
#|                 # Local recording: "no open file" means a new match started.
#|                 is_new_match = (not replay_file) if pusher is None \
#|                     else (cur_match_id != last_started_match_id)
#|                 if is_new_match:
#|                     start_replay(
#|                         map_name,
#|                         gi.get('gameMode', ''),
#|                         gi.get('elapsedTime', 0),
#|                         match_id=cur_match_id,
#|                     )
#|                     last_started_match_id = cur_match_id
#|                     pre_match_open_since = time.time() if is_pre_match_state else None
#|                     # read_all() already ran this tick before start_replay —
#|                     if isinstance(data.get('killEvents'), list):
#|                         data['killEvents'] = []
#|                     if isinstance(data.get('damageEvents'), list):
#|                         data['damageEvents'] = []
#|                 elif match_state == 'InProgress' and pre_match_open_since is not None:
#|                     # Round actually started — the pre-match safety valve
#|                     pre_match_open_since = None
#|                 elif is_pre_match_state and pre_match_open_since is not None:
#|                     waited = time.time() - pre_match_open_since
#|                     if waited > REPLAY_PREMATCH_MAX_WAIT_S:
#|                         logger.warning(
#|                             "Pre-match recording open %.0fs (> %.0fs cap) still "
#|                             "in %s — abandoning (deleting) empty-lobby replay.",
#|                             waited, REPLAY_PREMATCH_MAX_WAIT_S, match_state,
#|                         )
#|                         abandoned_path = replay_path
#|                         stop_replay()
#|                         if abandoned_path is not None:
#|                             try:
#|                                 Path(abandoned_path).unlink()
#|                             except OSError as exc:
#|                                 logger.warning(
#|                                     "Could not delete abandoned pre-match "
#|                                     "replay %s: %s", abandoned_path, exc,
#|                                 )
#|                         # Reset the dedup key so the very next tick (still
#|                         last_started_match_id = None
#|                         pre_match_open_since = None
#|             elif is_skipped_map:
#|                 if replay_file:
#|                     stop_replay()
#|                 pre_match_open_since = None
#|             elif match_state in ('WaitingPostMatch', 'LeavingMap', 'EndMatch'):
#|                 if replay_file:
#|                     # Defer the close until after this tick's snapshot is
#|                     close_after_write = True
#|                 pre_match_open_since = None
#|
#|             last_match_state = match_state
#|
#|             # Sanitize once; reuse for mmap, JSON, push, and replay outputs.
#|             sanitized = sanitize_nan(data)
#|             json_str = json.dumps(sanitized, ensure_ascii=False, indent=2 if args.pretty else None)
#|             json_bytes = json_str.encode('utf-8')
#|             # Compact form for push / replay (no indent); computed once.
#|             compact_json = (
#|                 json_str if not args.pretty
#|                 else json.dumps(sanitized, ensure_ascii=False)
#|             )
#|             # After serialising: whatever the mirror does, the bytes pushed
#|             if local_mirror is not None:
#|                 local_mirror.observe(sanitized)   # never raises
#|
#|             # Publish via shared memory first (zero-copy for HTTP readers).
#|             if mmap_writer is not None:
#|                 try:
#|                     mmap_writer.write(json_bytes)
#|                 except BodyTooLargeError:
#|                     new_capacity = max(mmap_capacity * 2, len(json_bytes) + 1_000_000)
#|                     logger.info(
#|                         "mmap capacity %d too small for %d-byte snapshot — "
#|                         "recreating at %d bytes",
#|                         mmap_capacity, len(json_bytes), new_capacity,
#|                     )
#|                     mmap_writer.close()
#|                     mmap_path = Path(args.output).with_suffix('.mmap')
#|                     # Wipe the stale file so the fresh header is unambiguous.
#|                     try:
#|                         mmap_path.unlink()
#|                     except OSError:
#|                         pass
#|                     mmap_capacity = new_capacity
#|                     mmap_writer = LiveDataWriter(mmap_path, capacity=mmap_capacity)
#|                     mmap_writer.write(json_bytes)
#|                 except OSError as e:
#|                     logger.warning("Data channel write failed: %s — disabling", e)
#|                     try:
#|                         mmap_writer.close()
#|                     except OSError:
#|                         pass
#|                     mmap_writer = None
#|
#|             # Always keep a human-readable JSON fallback on disk so external
#|             with open(args.output, 'w', encoding='utf-8') as f:
#|                 f.write(json_str)
#|
#|             # Push the compact snapshot to the central ingest server when
#|             if pusher is not None:
#|                 pusher._offset_health = reader._offset_health
#|                 try:
#|                     ok = pusher.push(compact_json.encode('utf-8'))
#|                 except Exception:
#|                     ok = False
#|                     # Never let a push bug stop memory reads.
#|                     logger.exception("ingest push raised")
#|                 if ok:
#|                     if _push_consec_fail > 0:
#|                         logger.info("ingest push recovered after %d consecutive failure(s)",
#|                                     _push_consec_fail)
#|                     _push_consec_fail = 0
#|                 else:
#|                     _push_consec_fail += 1
#|                     # First, third, then every 10th failure logged loud.
#|                     if _push_consec_fail in (1, 3) or _push_consec_fail % 10 == 0:
#|                         logger.warning("ingest push failing (%d consecutive)",
#|                                        _push_consec_fail)
#|
#|             # Write replay snapshot (compact, no indent) — reuse compact_json.
#|             if replay_file:
#|                 write_replay_snapshot(compact_json)
#|             # Now safe to close the post-match replay — the EndMatch /
#|             if close_after_write and replay_file:
#|                 stop_replay()
#|
#|             elapsed = gi['elapsedTime']
#|             tickets = ' '.join(f"T{t['id']}={t['tickets']}" for t in gi['teams'])
#|             player_count = len(data['players'])
#|             zone_count = len(data['captureZones'])
#|             veh_count = len(data['vehicles'])
#|             dep = data['deployables']
#|             fob_count = len(dep['fobs'])
#|             hab_count = len(dep['habs'])
#|             emp_count = len(dep['emplacements'])
#|             rally_count = len(dep.get('rallies', []))
#|             ammo_count = len(dep.get('ammoCrates', []))
#|             repair_count = len(dep.get('repairStations', []))
#|             fort_count = len(dep.get('fortifications', []))
#|             mine_count = len(dep.get('mines', []))
#|             cycle_dur = time.time() - cycle_start
#|
#|             # Rules: `_collect_objects` allocates millions of small
#|             main_loop_tick += 1
#|             if main_loop_tick % 10 == 0:
#|                 gc.collect()
#|
#|             rec = f" REC[{replay_snap_count}]" if replay_file else ""
#|             logger.info(
#|                 "%dm%02ds %s %s | P=%d Z=%d V=%d FOB=%d HAB=%d EMP=%d RAL=%d AMO=%d REP=%d FRT=%d MIN=%d | %.1fs%s",
#|                 elapsed // 60, elapsed % 60, gi['matchState'], tickets,
#|                 player_count, zone_count, veh_count,
#|                 fob_count, hab_count, emp_count, rally_count,
#|                 ammo_count, repair_count, fort_count, mine_count, cycle_dur, rec,
#|             )
#|
#|             # Tracemalloc periodic dump removed v0.79.5 — see comment at
#|
#|             if args.once:
#|                 sys.stdout.write(json_str + "\n")
#|                 break
#|
#|             # Successful cycle — clear the process-death counter.
#|             consec_read_err = 0
#|
#|             # Idle backoff during end-of-match states. Players are on the
#|             idle_multiplier = 6 if match_state in ('WaitingPostMatch', 'EndMatch') else 1
#|             sleep_time = max(0.1, (args.interval * idle_multiplier) - cycle_dur)
#|             if idle_multiplier == 1 and (replay_file or pusher is not None):
#|                 sleep_with_position_sampling(sleep_time, _elapsed_raw)
#|             else:
#|                 time.sleep(sleep_time)
#|         except KeyboardInterrupt:
#|             stop_replay()
#|             logger.info("Stopped by user (KeyboardInterrupt).")
#|             break
#|         except pymem.exception.MemoryReadError as exc:
#|             # Transient page-read failure (ERROR_PARTIAL_COPY 299 is the
#|             mem_err_count += 1
#|             consec_read_err += 1
#|             now = time.time()
#|             if now - mem_err_window_start >= MEM_ERR_SUMMARY_INTERVAL:
#|                 logger.warning(
#|                     "transient MemoryReadError x%d in last %.0fs (last: %s)",
#|                     mem_err_count, now - mem_err_window_start, exc,
#|                 )
#|                 mem_err_count = 0
#|                 mem_err_window_start = now
#|             # Process-death detection: after a few consecutive failures,
#|             if (consec_read_err >= CONSEC_READ_ERR_RECONNECT
#|                     and args.pid is None
#|                     and not _is_pid_alive(current_pid)):
#|                 logger.warning(
#|                     "Target PID=%s appears dead (server restart?) — "
#|                     "re-discovering…", current_pid,
#|                 )
#|                 stop_replay()
#|                 _close_reader_pm(reader)
#|                 current_pid = wait_for_squad_pid(reader_config)
#|                 reader = build_reader(current_pid)
#|                 _rebind_per_process_state(reader)
#|                 consec_read_err = 0
#|                 continue
#|             time.sleep(args.interval)
#|         except Exception:
#|             logger.exception("Read cycle failed")
#|             consec_read_err += 1
#|             if (consec_read_err >= CONSEC_READ_ERR_RECONNECT
#|                     and args.pid is None
#|                     and not _is_pid_alive(current_pid)):
#|                 logger.warning(
#|                     "Target PID=%s gone after exception — re-discovering…",
#|                     current_pid,
#|                 )
#|                 stop_replay()
#|                 _close_reader_pm(reader)
#|                 current_pid = wait_for_squad_pid(reader_config)
#|                 reader = build_reader(current_pid)
#|                 _rebind_per_process_state(reader)
#|                 consec_read_err = 0
#|                 continue
#|             time.sleep(args.interval)
#|
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
#|
#| # Exit codes that mean "configuration is broken — restarting won't help".
#| _NORESTART_EXIT_CODES = frozenset({2, 3, 4, 7})
#|
#| # Circuit breaker — if the reader keeps crashing this many times in a
#| _MAX_CONSECUTIVE_CRASHES = 50
#|
#| # A clean run for this long resets the consecutive-crash counter, so a
#| _HEALTHY_RUN_THRESHOLD_SECONDS = 60.0
#|
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
#|
#|         if consecutive_crashes >= _MAX_CONSECUTIVE_CRASHES:
#|             logger.fatal(
#|                 "Reader crashed %d times in a row without a healthy run "
#|                 "(>=%ds). Giving up — fix the deploy and restart manually.",
#|                 consecutive_crashes, int(_HEALTHY_RUN_THRESHOLD_SECONDS),
#|             )
#|             return 1
#|
#|         # Exponential backoff capped at 60s. Sequence: 2, 4, 8, 16, 32,
#|         delay = min(60, 2 ** min(consecutive_crashes, 6))
#|         logger.info("Restarting service in %ds", delay)
#|         try:
#|             time.sleep(delay)
#|         except KeyboardInterrupt:
#|             logger.info("KeyboardInterrupt during backoff — clean exit")
#|             return 0
#|
#| if __name__ == '__main__':
#|     sys.exit(_supervised_main())
