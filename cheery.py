import asyncio
import struct
import random
import logging

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    _LOOP = "uvloop"
except ImportError:
    _LOOP = "asyncio (install uvloop for 2x speed: pip install uvloop)"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Commands (client → server) ─────────────────────────────────────────────
CREATE     = 0x01
JOIN       = 0x02
OFFER      = 0x03
ANSWER     = 0x04
ICE        = 0x05
FIND_MATCH = 0x06  # Request matchmaking with role preference

# ── Responses (server → client) ────────────────────────────────────────────
ROOM_CREATED = 0x10
JOIN_OK      = 0x11
MATCH_FOUND  = 0x12  # Match found, includes room code and role
WAITING      = 0x13  # Waiting for opponent
OFFER_FWD    = 0x20
ANSWER_FWD   = 0x21
ICE_FWD      = 0x22
ERROR        = 0x7F

# ── Shared state ───────────────────────────────────────────────────────────
# rooms[code] = {"creator": (reader, writer) | None,
#                "joiner":  (reader, writer) | None}
# Freed automatically when both peers disconnect.
rooms: dict[int, dict] = {}

# ── Matchmaking queues ─────────────────────────────────────────────────────
chasers_queue = []  # (reader, writer) tuples waiting to be chaser
runners_queue = []  # (reader, writer) tuples waiting to be runner
any_queue = []      # (reader, writer) tuples with no preference


# ── Helpers ────────────────────────────────────────────────────────────────

async def send_frame(writer: asyncio.StreamWriter, cmd: int, payload: bytes = b"") -> None:
    """Write a length-prefixed frame and flush."""
    writer.write(bytes([cmd]) + struct.pack("<I", len(payload)) + payload)
    await writer.drain()


async def send_error(writer: asyncio.StreamWriter) -> None:
    await send_frame(writer, ERROR)


def _unique_room_code() -> int:
    """Return a 6-digit code that isn't already in use."""
    while True:
        code = random.randint(100_000, 999_999)
        if code not in rooms:
            return code


def _cleanup_room(room_code: int, is_creator: bool) -> None:
    """
    Mark this peer's slot as None.
    Delete the room only when BOTH slots are empty so the surviving
    peer isn't silently orphaned.
    """
    if room_code not in rooms:
        return
    room = rooms[room_code]
    if is_creator:
        room["creator"] = None
    else:
        room["joiner"] = None
    if room["creator"] is None and room["joiner"] is None:
        rooms.pop(room_code, None)
        logger.info("🗑  Room %s removed", room_code)


def _remove_from_queues(reader, writer) -> None:
    """Remove a client from all matchmaking queues."""
    for queue in [chasers_queue, runners_queue, any_queue]:
        for i, (r, w) in enumerate(queue):
            if r is reader and w is writer:
                queue.pop(i)
                logger.debug("Removed client from queue (size now: %d)", len(queue))
                return


async def matched_pair(chaser_reader, chaser_writer, 
                       runner_reader, runner_writer,
                       chaser_first: bool = True) -> None:
    """
    Notify both clients they've been matched.
    
    Creates a room and tells each client their assigned role.
    The chaser always gets role=0, runner gets role=1.
    Sets up the room for P2P relay (OFFER/ANSWER/ICE forwarding).
    """
    room_code = _unique_room_code()
    rooms[room_code] = {"creator": None, "joiner": None}
    
    # Tell chaser: room_code + role 0 (chaser)
    payload = struct.pack("<I", room_code) + bytes([0])
    await send_frame(chaser_writer, MATCH_FOUND, payload)
    logger.info("🎯 Chaser matched in room %s", room_code)
    
    # Tell runner: room_code + role 1 (runner)
    payload = struct.pack("<I", room_code) + bytes([1])
    await send_frame(runner_writer, MATCH_FOUND, payload)
    logger.info("🏃 Runner matched in room %s", room_code)
    
    # Set up room for P2P relay
    # Chaser is always the "creator" (hosts P2P)
    rooms[room_code]["creator"] = (chaser_reader, chaser_writer)
    rooms[room_code]["joiner"] = (runner_reader, runner_writer)
    
    logger.info("🏠 Room %s created for matched pair", room_code)


# ── Main handler ───────────────────────────────────────────────────────────

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer       = writer.get_extra_info("peername")
    room_code  = None
    is_creator = False

    logger.info("🔌 Connected  %s", peer)

    try:
        while True:
            # Every message starts with a 1-byte command.
            cmd_byte = await reader.read(1)
            if not cmd_byte:           # clean EOF
                break
            cmd = cmd_byte[0]

            # ── FIND_MATCH ────────────────────────────────────────────────
            if cmd == FIND_MATCH:
                # Read the 4-byte length prefix first
                len_bytes = await reader.readexactly(4)
                payload_len = struct.unpack("<I", len_bytes)[0]
                
                # Then read the payload (should be 1 byte for role)
                role_bytes = await reader.readexactly(payload_len)
                role = role_bytes[0]  # 0=chaser, 1=runner, 2=any
                
                role_names = ["chaser", "runner", "any"]
                role_name = role_names[role] if role < len(role_names) else "unknown"
                logger.info("🔍 %s looking for match as %s", peer, role_name)
                
                matched = False
                
                # Try to match immediately
                if role == 0:  # Wants to be chaser
                    if runners_queue:
                        runner_reader, runner_writer = runners_queue.pop(0)
                        await matched_pair(reader, writer, runner_reader, runner_writer)
                        matched = True
                    elif any_queue:
                        any_reader, any_writer = any_queue.pop(0)
                        await matched_pair(reader, writer, any_reader, any_writer)
                        matched = True
                    else:
                        chasers_queue.append((reader, writer))
                        await send_frame(writer, WAITING)
                        logger.info("⏳ %s waiting in chaser queue (size: %d)", 
                                  peer, len(chasers_queue))
                        
                elif role == 1:  # Wants to be runner
                    if chasers_queue:
                        chaser_reader, chaser_writer = chasers_queue.pop(0)
                        await matched_pair(chaser_reader, chaser_writer, reader, writer)
                        matched = True
                    elif any_queue:
                        any_reader, any_writer = any_queue.pop(0)
                        await matched_pair(any_reader, any_writer, reader, writer, 
                                         chaser_first=False)
                        matched = True
                    else:
                        runners_queue.append((reader, writer))
                        await send_frame(writer, WAITING)
                        logger.info("⏳ %s waiting in runner queue (size: %d)", 
                                  peer, len(runners_queue))
                        
                else:  # Any role (2)
                    if chasers_queue:
                        chaser_reader, chaser_writer = chasers_queue.pop(0)
                        await matched_pair(chaser_reader, chaser_writer, reader, writer)
                        matched = True
                    elif runners_queue:
                        runner_reader, runner_writer = runners_queue.pop(0)
                        await matched_pair(reader, writer, runner_reader, runner_writer)
                        matched = True
                    else:
                        any_queue.append((reader, writer))
                        await send_frame(writer, WAITING)
                        logger.info("⏳ %s waiting in any queue (size: %d)", 
                                  peer, len(any_queue))

            # ── CREATE ────────────────────────────────────────────────────
            elif cmd == CREATE:
                if room_code is not None:
                    # Already in a room — reject double-create.
                    await send_error(writer)
                    continue

                room_code  = _unique_room_code()
                is_creator = True
                rooms[room_code] = {"creator": (reader, writer), "joiner": None}

                await send_frame(writer, ROOM_CREATED, struct.pack("<I", room_code))
                logger.info("🏠 Room %s created by %s", room_code, peer)

            # ── JOIN ──────────────────────────────────────────────────────
            elif cmd == JOIN:
                code_bytes = await reader.readexactly(4)
                code = struct.unpack("<I", code_bytes)[0]

                if room_code is not None:
                    await send_error(writer)
                    continue

                if code not in rooms or rooms[code]["joiner"] is not None:
                    await send_error(writer)
                    continue

                room_code  = code
                is_creator = False
                rooms[room_code]["joiner"] = (reader, writer)

                await send_frame(writer, JOIN_OK)
                logger.info("🔑 Room %s joined by %s", room_code, peer)

            # ── OFFER / ANSWER / ICE ──────────────────────────────────────
            elif cmd in (OFFER, ANSWER, ICE):
                len_bytes = await reader.readexactly(4)
                size      = struct.unpack("<I", len_bytes)[0]
                payload   = await reader.readexactly(size)

                if room_code not in rooms:
                    await send_error(writer)
                    continue

                room   = rooms[room_code]
                target = room["joiner"] if is_creator else room["creator"]

                if target is None:
                    # Peer hasn't joined yet or already left — silently drop.
                    continue

                _, target_writer = target

                if cmd == OFFER:
                    await send_frame(target_writer, OFFER_FWD, payload)
                    logger.debug("📤 OFFER forwarded in room %s", room_code)
                elif cmd == ANSWER:
                    await send_frame(target_writer, ANSWER_FWD, payload)
                    logger.debug("📤 ANSWER forwarded in room %s", room_code)
                else:
                    await send_frame(target_writer, ICE_FWD, payload)
                    logger.debug("📤 ICE forwarded in room %s", room_code)

            # ── Unknown command ───────────────────────────────────────────
            else:
                logger.warning("❓ Unknown command 0x%02x from %s", cmd, peer)
                await send_error(writer)

    except asyncio.IncompleteReadError:
        pass   # peer closed mid-frame
    except ConnectionResetError:
        pass
    except Exception as exc:
        logger.exception("💥 Unexpected error from %s: %s", peer, exc)
    finally:
        # Clean up matchmaking queues if client was waiting
        _remove_from_queues(reader, writer)
        
        if room_code is not None:
            _cleanup_room(room_code, is_creator)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("🔌 Disconnected %s", peer)


# ── Entry point ────────────────────────────────────────────────────────────

async def main() -> None:
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8766)
    addrs  = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info("✅ Server running on %s  [event loop: %s]", addrs, _LOOP)
    logger.info("🎮 Matchmaking enabled: Chasers ↔ Runners")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped")