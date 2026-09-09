"""examples/read_and_write.py — illustrative excerpt, not the full source.

This is real logic taken from the production reader, trimmed to two
representative functions: one read path, and the one write path that
exists anywhere in this codebase. Every literal memory offset has been
redacted (replaced with a named placeholder, no value) — the mechanism is
real, the exact struct layout is not included.

Both functions run against `r.pm`, which is `agent/memory_backend.py`'s
pymem-compatible backend: `process_vm_readv` for reads, `process_vm_writev`
for writes. See that file for the actual syscall-level mechanism, which
has no offsets in it at all — it's a generic "read/write N bytes at this
address in another process" backend, and there's nothing to redact.

------------------------------------------------------------------------
Read example — following a chain of pointers to a string value.
Real source: queue_priority.py's _beacon_eos(). Offsets redacted.
------------------------------------------------------------------------
"""

CLIENT_BEACON_CONN_OFF = None   # redacted — real value is a fixed struct offset
NET_PLAYER_ID_OFF = None        # redacted
PER_INST_OFF_IN_PLAYERID = None  # redacted
EOS_STRING_DATA_OFF = None      # redacted
EOS_STRING_NUM_OFF = None       # redacted

PTR_MIN, PTR_MAX = 0x100000000, 0x800000000000  # plausible-userspace-pointer
                                                  # bounds check, not a struct
                                                  # offset — same on every
                                                  # 64-bit Linux process


def _beacon_eos(r, beacon_ptr: int) -> str | None:
    """Read one player's EOS account ID string out of the beacon's own
    connection/player-id chain. Three chained pointer reads, then a
    length-checked UTF-16 string read — no writes."""
    net_conn = r._r64(beacon_ptr + CLIENT_BEACON_CONN_OFF)
    if not (PTR_MIN < net_conn < PTR_MAX):
        return None
    per_inst = r._r64(net_conn + NET_PLAYER_ID_OFF + PER_INST_OFF_IN_PLAYERID)
    if not (PTR_MIN < per_inst < PTR_MAX):
        return None
    str_data = r._r64(per_inst + EOS_STRING_DATA_OFF)
    str_num = r._r32(per_inst + EOS_STRING_NUM_OFF)
    if not (PTR_MIN < str_data < PTR_MAX) or not (1 <= str_num <= 64):
        return None
    raw = r.pm.read_bytes(str_data, str_num * 2)  # <- the actual read call
    eos = raw.decode("utf-16-le", errors="replace").rstrip("\x00").lower()
    if len(eos) == 32 and all(c in "0123456789abcdef" for c in eos):
        return eos
    return None


"""
------------------------------------------------------------------------
Write example — the ONLY place this codebase writes to the game
process's memory. Real source: queue_priority.py's _shift_to_target().
Offsets redacted.

What it does: repositions a specific player ahead of others in Squad's
own native join queue, by directly rewriting the queue slot array (an
in-place block move) and then patching each shifted player's own
client-side "my position in queue" field so their UI reflects the move
immediately. It moves existing, real slot data around — it does not
invent, duplicate, or delete a queue entry.
------------------------------------------------------------------------
"""

SLOT_SIZE = None              # redacted — bytes per queue-array entry
SLOT_CLIENT_BEACON_OFF = None  # redacted — offset of the client pointer within a slot
CLIENT_QUEUE_POS_OFF = None    # redacted — offset of the client's own "my queue position" field


def _shift_to_target(r, data_ptr: int, src_idx: int, target_idx: int) -> int:
    """Move the queue entry at src_idx to target_idx, shifting everything
    in between back by one slot — same as if that player had joined
    earlier. Returns how many clients' own position field got updated."""
    if target_idx >= src_idx:
        return 0
    block_size = (src_idx - target_idx + 1) * SLOT_SIZE
    affected = 0
    block = r.pm.read_bytes(data_ptr + target_idx * SLOT_SIZE, block_size)
    target_slot = block[(src_idx - target_idx) * SLOT_SIZE:
                         (src_idx - target_idx + 1) * SLOT_SIZE]
    front_slots = block[:(src_idx - target_idx) * SLOT_SIZE]

    # The actual write: move the target player's slot to the front of the
    # affected range, shift everyone else back by one — an in-place
    # reordering of real slots, nothing fabricated or duplicated.
    r.pm.write_bytes(data_ptr + target_idx * SLOT_SIZE,
                      target_slot + front_slots, block_size)

    fresh = r.pm.read_bytes(data_ptr + target_idx * SLOT_SIZE, block_size)
    for new_pos_zero in range(src_idx - target_idx + 1):
        import struct
        cptr = struct.unpack_from("<Q", fresh, new_pos_zero * SLOT_SIZE + SLOT_CLIENT_BEACON_OFF)[0]
        if PTR_MIN < cptr < PTR_MAX:
            # Second write: tell that client what their new position is,
            # so their own queue UI updates without waiting for a full
            # server broadcast.
            r.pm.write_bytes(cptr + CLIENT_QUEUE_POS_OFF,
                              struct.pack("<i", target_idx + new_pos_zero + 1), 4)
            affected += 1
    return affected
