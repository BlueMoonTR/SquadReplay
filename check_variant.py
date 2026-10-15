"""Prove an agent variant cannot do what its name says it does not do.

    python _dev/agent_variant_check.py --variant read  FILE_OR_DIR...
    python _dev/agent_variant_check.py --variant read-voice  dist/squadreplay-agent-read-voice.py

The agent ships in variants (docs/agent-variants.md). "Read-only" is only
worth saying if the file the operator runs has no way to write -- so this
looks for the ways, not for names. A release whose read-only artefact
trips any rule below is not published.

Write primitives (forbidden unless the variant contains ``write``):
  * process_vm_writev -- referenced, called, or looked up by string
  * ptrace -- PTRACE_POKEDATA/POKETEXT write memory too
  * raw libc ``syscall`` -- would bypass both of the above
  * opening ``/proc/<pid>/mem`` in any mode but ``rb``
  * importing agent.memory_write (the agent's one write module)

Kernel probes (forbidden unless the variant contains ``voice``):
  * attach_uprobe / bpf_program__attach_uprobe / bpf() / libbpf / bcc

Rules run on the Python AST plus a plain-text pass for names spelled out
as strings (``getattr(libc, "process_vm_writev")``). Exit code 1 on any
finding; each one is printed as ``file:line: rule: detail``.
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

WRITE_NAMES = {"process_vm_writev", "ptrace", "syscall"}
# The queue code's own names: the primitive is only half of "can write" --
# a read variant that still builds a QueuePriority enforcer has the wiring
# even if the module it imports is missing.
WRITE_WIRING = {"QueuePriority", "queue_enforcer"}
WRITE_MODULES = {"agent.memory_write", "queue_priority"}
# Substrings that only ever mean a write. ("ptrace" alone is not one: the
# installer's sysctl is kernel.yama.ptrace_scope and its capability is
# cap_sys_ptrace; a string that IS exactly a primitive's name -- a
# getattr(libc, "ptrace") lookup -- is caught by the exact-name rule.)
WRITE_STRINGS = ("process_vm_writev", "PTRACE_POKE",
                 # eBPF helpers that act on the probed process rather than
                 # just read it -- a voice program must never carry these.
                 "bpf_probe_write_user", "bpf_send_signal")

PROBE_NAMES = {"attach_uprobe", "attach_uretprobe", "bpf_program__attach_uprobe",
               "bpf_program__attach_uprobe_opts", "bpf_prog_load", "bpf"}
PROBE_MODULES = {"bcc", "agent.voice_tap"}
PROBE_STRINGS = ("attach_uprobe", "libbpf.so", "bpf_prog_load")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.detail}"


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


def _open_mode(call: ast.Call) -> str | None:
    if len(call.args) >= 2:
        return _const_str(call.args[1])
    for kw in call.keywords:
        if kw.arg == "mode":
            return _const_str(kw.value)
    return "r"   # open()'s default


class _Scanner(ast.NodeVisitor):
    def __init__(self, path: str, allow_write: bool, allow_probe: bool):
        self.path = path
        self.allow_write = allow_write
        self.allow_probe = allow_probe
        self.found: list[Finding] = []

    def _add(self, node: ast.AST, rule: str, detail: str) -> None:
        self.found.append(Finding(self.path, getattr(node, "lineno", 0), rule, detail))

    def _name(self, node: ast.AST, name: str) -> None:
        if not self.allow_write and name in WRITE_NAMES:
            self._add(node, "write-primitive", name)
        if not self.allow_write and name in WRITE_WIRING:
            self._add(node, "write-wiring", name)
        if not self.allow_probe and name in PROBE_NAMES:
            self._add(node, "kernel-probe", name)

    def _module(self, node: ast.AST, module: str) -> None:
        for forbidden, allowed, rule in ((WRITE_MODULES, self.allow_write, "write-module"),
                                         (PROBE_MODULES, self.allow_probe, "probe-module")):
            if allowed:
                continue
            for m in forbidden:
                if module == m or module.startswith(m + "."):
                    self._add(node, rule, module)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._module(node, alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        self._module(node, base)
        for alias in node.names:   # `from agent import memory_write`
            self._module(node, f"{base}.{alias.name}" if base else alias.name)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._name(node, node.attr)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._name(node, node.id)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open" and node.args:
            target = _const_str(node.args[0]) or ""
            mode = _open_mode(node)
            if "/proc/" in target and target.rstrip("'\"").endswith("/mem"):
                if mode is None or any(c in mode for c in "wa+x"):
                    if not self.allow_write:
                        self._add(node, "write-primitive",
                                  f"open(/proc/<pid>/mem, {mode!r})")
        self.generic_visit(node)


def _text_pass(path: str, source: str, allow_write: bool, allow_probe: bool):
    """Names spelled out as strings slip past the AST name checks.
    Comments and docstrings are text too, so only string LITERALS count."""
    out: list[Finding] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings:
            continue
        text = node.value
        if not allow_write:
            if text.strip() in WRITE_NAMES:
                out.append(Finding(path, node.lineno, "write-primitive", f"string {text.strip()!r}"))
            for s in WRITE_STRINGS:
                if s in text:
                    out.append(Finding(path, node.lineno, "write-primitive", f"string {s!r}"))
        if not allow_probe:
            if text.strip() in PROBE_NAMES:
                out.append(Finding(path, node.lineno, "kernel-probe", f"string {text.strip()!r}"))
            for s in PROBE_STRINGS:
                if s in text:
                    out.append(Finding(path, node.lineno, "kernel-probe", f"string {s!r}"))
    return out


def scan_source(path: str, source: str, variant: str) -> list[Finding]:
    caps = set(variant.split("-"))
    allow_write = "write" in caps
    allow_probe = "voice" in caps
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [Finding(path, exc.lineno or 0, "unparseable", str(exc))]
    sc = _Scanner(path, allow_write, allow_probe)
    sc.visit(tree)
    found = sc.found + _text_pass(path, source, allow_write, allow_probe)
    # One finding per (line, rule, detail): `libc.process_vm_writev`
    # is both an Attribute and its own string in the text pass.
    seen, out = set(), []
    for f in sorted(found, key=lambda f: (f.path, f.line, f.rule, f.detail)):
        key = (f.path, f.line, f.rule)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def scan_bundle(path, variant: str) -> list[Finding]:
    """Scan a one-file variant the way its modules will actually run.

    The embedded modules are stored as ``#|`` comment lines so the file stays
    valid, readable Python -- which means an AST pass over the FILE sees only
    the bootstrap and is blind to everything that matters. So this reads each
    embedded module back out and scans it as the Python it is."""
    import bundle_bootstrap
    modules, _digest = bundle_bootstrap.read_embedded(str(path))
    found: list[Finding] = []
    for name in sorted(modules):
        mod = modules[name]
        found += scan_source(f"{Path(path).name}::{mod.relpath}", mod.source, variant)
    # and the bootstrap itself, which is real code at the top of the file
    # (a section starts at a line that BEGINS with the marker; the bootstrap
    # also spells the marker out in its own code, mid-line)
    head_lines = []
    for line in Path(path).read_text(encoding="utf-8").splitlines(True):
        if line.startswith(bundle_bootstrap.MARK):
            break
        head_lines.append(line)
    found += scan_source(f"{Path(path).name}::<bootstrap>", "".join(head_lines), variant)
    return found


def scan_paths(paths, variant: str) -> list[Finding]:
    found: list[Finding] = []
    for p in map(Path, paths):
        files = sorted(p.rglob("*.py")) if p.is_dir() else [p]
        for f in files:
            found += scan_source(str(f), f.read_text(encoding="utf-8"), variant)
    return found


VARIANTS = ("read", "read-write", "read-voice", "read-write-voice")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--variant", required=True, choices=VARIANTS)
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args(argv)
    found = scan_paths(args.paths, args.variant)
    for f in found:
        print(f)
    if found:
        print(f"{len(found)} finding(s): this is not a {args.variant!r} build", file=sys.stderr)
        return 1
    print(f"ok: nothing in {len(args.paths)} path(s) exceeds {args.variant!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
