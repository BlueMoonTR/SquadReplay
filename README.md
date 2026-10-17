# SquadReplay Agent

The SquadReplay agent runs on a Squad dedicated server and feeds match data
to [SquadReplay](https://squadreplay.com): replays, the live map, player
statistics and leaderboards.

This repository is where that agent is published, so that a server owner can
read what they are about to run before they run it — what it reads, the one
thing it can write, how it talks to the central server, and the memory
access it needs.

> **Status.** All four variants are published here as a single file each
> (`squadreplay-agent-<variant>.py`), the concise build — code and one-line
> summaries, with the long rationale kept in the project repository. The file is
> plain text: read it before you run it, and `python3 <file> --bundle-info` lists
> the modules it contains.
>
> For the **voice** variants, `--install` sets up the host prerequisites: it
> installs `python3-bpfcc` and writes a narrow sudoers rule that lets the agent
> run the capture tap as root (it needs `CAP_BPF`/`CAP_PERFMON`), pinned to the
> system `python3` and the exact tap path — not a general root grant. The
> community must still be cleared for voice on the central server. Without the
> prerequisites or the clearance the voice variant still reads and pushes; it
> just does not capture. See [Voice](#voice) and [LEGAL.md](LEGAL.md).

## Variants

Each variant is a single file. Pick the one that does only what you are
willing to allow on your server — the SquadReplay platform works with any
of them.

| Variant | Reads match data | Writes to the game | Voice |
|---|:-:|:-:|:-:|
| `read` | ✓ | — | — |
| `read-write` | ✓ | queue priority | — |
| `read-voice` | ✓ | — | ✓ |
| `read-write-voice` | ✓ | queue priority | ✓ |

- **read** is all the platform needs: replays, the live map, statistics and
  leaderboards all come from reading.
- **write** adds one feature and nothing else — *queue priority*, which
  moves a priority player up Squad's own join queue by writing to that
  queue in memory. It is the only thing any variant ever writes.
- **voice** adds capture of players' in-game voice for positional playback
  in the replay viewer. It is gated — see [Voice](#voice) below.

### A variant is what its file contains, not a setting

"Read-only" is only worth saying if it is true of the file you run. So a
`read` variant is built **without** the write code: there is no
`process_vm_writev`, no writable open of `/proc/<pid>/mem`, no write module
to import. You do not have to trust a flag — you can `grep` the file. The
same holds for voice: a non-voice variant carries no capture code at all.

Every release is checked this way before it is published, and the checker
ships alongside the variant files so you can run it yourself against a file
you downloaded.

## Install

Setting up an agent has two sides: the SquadReplay operator issues you a
one-time enrollment token, and you run the variant on your own Squad host.

**1. Get an enrollment token.** Ask the SquadReplay operator for one — they run
`ingest.provision enroll-token <your-agent-id>` on the central server. It is
single-use and ties this host to your community.

**2. Download the variant you want** (see [Which variant?](#which-variant)
below), e.g. `squadreplay-agent-read.py`. It is one file; there is nothing else
to download.

**3. Read it**, if you want to know what it does. A `read` file has no code that
writes to the game process; the voice code is only in the `voice` variants.

**4. Install** as root (it needs to set `kernel.yama.ptrace_scope`, apply file
capabilities, and write a restart script):

```sh
sudo python3 squadreplay-agent-read.py --install --enroll <token>
```

`--install` auto-detects the running `SquadGameServer`, chooses a deploy
directory (default `~/BOTS/SquadReplay` of the Squad user; override with
`--deploy-dir`), creates the local stats file
([`player-stats.sqlite`](#your-own-copy-of-the-stats-player-statssqlite)),
and provisions the agent with central. It is idempotent —
safe to re-run as a repair step. A **voice** variant additionally installs
`python3-bpfcc` and a narrow sudoers rule for the capture tap, and asks you to
accept the data-controller responsibility ([LEGAL.md](LEGAL.md)); pass
`--accept-legal` to accept non-interactively. Use `--force-user <user>` if
several Squad servers run under different accounts on the host.

**5. Start it.** `--install` writes `start.sh` (its own restart loop) in the
deploy directory but does not start the agent — that is your call:

```sh
cd ~/BOTS/SquadReplay && ./start.sh
```

There is no systemd unit; run it under `screen` / `tmux`, or add a
`cron @reboot` entry, if you want it to survive logout or reboot.

### Which variant?

- **`read`** — start here. Replays, the live map, statistics and leaderboards
  all come from reading; it is all the platform needs.
- **`read-write`** — also moves priority players up Squad's own join queue
  (*queue priority*). That queue write is the only thing any variant writes to
  the game.
- **`read-voice`** — also captures in-game voice for positional playback in the
  replay viewer. Needs `python3-bpfcc` on the host and the community cleared for
  voice on central; read [Voice](#voice) and [LEGAL.md](LEGAL.md) first.
- **`read-write-voice`** — both of the above.

To switch later, install a different variant file over the same deploy
directory.

## What it reads

On an interval the agent reads, from the running `SquadGameServer` process:

- player names and clan tags, and player identifiers (Epic Online Services
  ID; SteamID is matched on the central side over RCON),
- positions, teams, squads, roles, health, vehicle and weapon use,
- kill, wound and damage events, and match and player statistics,
- in-game chat and join/leave events,
- **voice variants only:** in-game voice chat and who is speaking.

## What it writes

One feature, in the `write` variants only: **queue priority**. When
enabled, it moves specified players ahead of others in Squad's native join
queue by writing to that queue's memory. Nothing else in any variant writes
to your process. The `read` variants cannot do this — they are built
without the code for it.

## Your own copy of the stats: `player-stats.sqlite`

Every variant keeps a local SQLite file, `player-stats.sqlite`, in the
agent's directory (`--install` creates it). It holds every match your server
plays, with the same per-player numbers the SquadReplay leaderboard shows —
they are computed by the same code from the same snapshots:

- `match` — layer, mode, factions, tickets, winner, duration;
  `complete = 1` once the match's end was seen
- `player` — EOS ID, last name, clan tag
- `match_player` — per player per match: kills, deaths, wounds, teamkills,
  vehicle kills and the infantry / vehicle split of each, revives, heals,
  scores, time played / as squad leader / fireteam leader / commander / in a
  squad, distance on foot and driving, longest kill (and its weapon),
  supplies delivered, FOBs and HABs built, rallies placed, FOBs destroyed,
  vehicle damage, captures, defenses, and seconds spent talking on each
  voice net (local, squad, squad-leader command net, squad leader →
  commander, commander → squad) — read from the game state every tick,
  no voice recording involved
  — and, for squad leaders, the objective points their squad scored while
  they led it (credited tick by tick to whoever was SL at the time)
  and their SL time per squad name (a squad renamed mid-match is split)
- `kill_event` — every kill: killer, victim, weapon, distance, vehicles
- `vehicle_session` — who sat in which vehicle seat, for how long

A running match is written once a minute and finalised when it ends; a
restart of the agent resumes it. ELO is not in it (it is computed centrally)
and neither are SteamIDs (they come from RCON, on the central side).

```sh
sqlite3 player-stats.sqlite \
  "SELECT p.last_name, SUM(mp.kills), SUM(mp.deaths), SUM(mp.rallies_placed)
   FROM match_player mp JOIN player p USING (eos_id)
   GROUP BY mp.eos_id ORDER BY 2 DESC LIMIT 10"
```

The file holds player identifiers and names, so it is created readable by
the agent's user only (`0600`). Keeping it is your responsibility as the data
controller ([LEGAL.md](LEGAL.md)) — a player's erasure request covers it too.
`--no-local-db` turns it off; `--local-db PATH` puts it elsewhere.

## How it reaches your process

The agent reads (and, for queue priority, writes) through
`process_vm_readv` / `process_vm_writev`, with `/proc/<pid>/mem` as a
fallback. It needs permission to access the game process's memory: either
run it as the **same user** as the Squad server with
`kernel.yama.ptrace_scope = 0`, or grant the binary `CAP_SYS_PTRACE` and
`CAP_DAC_READ_SEARCH`. The installer sets this up and shows you what it is
doing.

## What is not in this file

The Squad-specific part of the reader — the memory offsets and the
reverse-engineering behind them — is **not** in the downloadable agent and
is not published. It reaches the agent at runtime as a **signed, encrypted
payload** from the central server: the agent verifies it against a public
key built into the agent before loading it, so a compromised server cannot
push code the agent will run. The open file is the loader: process
discovery, the memory mechanism, install, enrolment, the network protocol,
auto-update, logging. The wider SquadReplay product — the web dashboard,
auth, the replay browser, RCON, the Discord bot — runs centrally, not on
your machine, and is not here.

Since 0.86.0 the tick itself — what one pass over the game's memory means — is
part of that signed payload too. What stays in this file is the loop that
drives it, and every byte that leaves your machine passes through two
functions you can read here: `_publish` (the local statistics copy, the local
shared-memory channel and the encrypted push to central) and `_push_position`
(the 4 Hz position frames, through the same connection).

None of that changes what happens to your process's memory, which is the
question this repository exists to answer.

## Voice

The voice variants are enabled only for communities that have taken on the
legal responsibility for recording their players' voice. **The server owner
is the data controller** for that data under the GDPR and Turkey's KVKK:
you must inform your players and obtain their explicit consent before voice
is recorded. The central server serves the voice payload only to a
community that has been cleared for it.

Read **[LEGAL.md](LEGAL.md) before installing any variant** — it sets out
these obligations and includes a player privacy-notice template.

## Licence

See [LICENSE](LICENSE) (SquadReplay Agent Source-Available License 1.1). The
source is published so you can read and audit it, and run it **unmodified** on
your own Squad server. You may not run a modified copy against the SquadReplay
central server, send it data the unmodified agent did not read from your game
server, redistribute the agent, or extract and keep the code the central server
delivers to a running agent. This is not an open-source license.
