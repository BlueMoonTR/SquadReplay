# agent/ — the process-access mechanism

Three files, no memory offsets in any of them (offsets live in the full
reader, which isn't part of this excerpt — see the repo root README).

- `memory_backend.py` — the actual mechanism: `process_vm_readv` for
  reads, `process_vm_writev` for writes, via `ctypes` against libc.
  Presented as a pymem-compatible shim (`self.pm.read_bytes(...)` /
  `self.pm.write_bytes(...)`) so the calling code — see
  `examples/read_and_write.py` at the repo root — doesn't need the real,
  Windows-only `pymem` package.
- `_platform.py` — `/proc`-based discovery of the running
  `SquadGameServer` process (`find_pid`, `is_pid_alive`).
- `_install.py` — where the `ptrace` access actually gets requested:
  `kernel.yama.ptrace_scope=0` + `setcap cap_sys_ptrace,cap_dac_read_search`
  on the binary. If you're deciding whether to grant this, this is the
  file to read.

Reading order: `_install.py` (what's being asked for) →
`memory_backend.py` (what that access is used to do) → `_platform.py`
(how the target process is found).
