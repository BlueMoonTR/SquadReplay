# SquadReplay Agent — memory access, shown

This repo exists for one purpose: to answer, honestly and concretely,
"what does the SquadReplay agent do to my `SquadGameServer` process's
memory?"

## What it does

- **Reads.** On an interval, the agent reads player positions, vehicle
  state, kill events, and match state out of the running
  `SquadGameServer` process's memory. See `examples/read_and_write.py`
  for a real read function, trimmed and with its exact memory offsets
  redacted.
- **Writes — one place, one purpose.** A single optional feature
  (queue priority) repositions specific players ahead of others in
  Squad's own native join queue, by directly rewriting that queue's data
  in memory. Nothing else in this codebase writes to your process.
  See the same example file for the real write function.
- **How it gets access.** `agent/_install.py` is the actual code that
  requests `ptrace` permission (`cap_sys_ptrace`) on install — read this
  if you want to see exactly what's being asked for. `agent/_platform.py`
  finds the target process; `agent/memory_backend.py` is the low-level
  read/write mechanism itself (`process_vm_readv`/`process_vm_writev`),
  and has no offsets in it at all — it's generic.

## What's not here, on purpose

The full reader (thousands of lines, hundreds of memory offsets specific
to Squad's current build) isn't included — those offsets are the result
of extensive reverse-engineering and aren't published. Also not here: the
network protocol and encryption used to talk to a central server, offset
provisioning, auto-update, enrollment, and everything about the wider
SquadReplay product (web dashboard, auth, billing, replay browser, RCON
integration, Discord bot) that runs centrally, not on your machine. None
of it changes what happens to your process's memory, which is the only
question this repo answers.

## LICENSE

Read it, audit it. It does not grant rights to rebuild or redistribute
the full agent from this excerpt.
