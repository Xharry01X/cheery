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
CREATE = 0x01
JOIN   = 0x02
OFFER  = 0x03
ANSWER = 0x04
ICE    = 0x05

# ── Responses (server → client) ────────────────────────────────────────────
ROOM_CREATED = 0x10
JOIN_OK      = 0x11
OFFER_FWD    = 0x20
ANSWER_FWD   = 0x21
ICE_FWD      = 0x22
ERROR        = 0x7F

# ── Shared state ───────────────────────────────────────────────────────────
# rooms[code] = {"creator": (reader, writer) | None,
#                "joiner":  (reader, writer) | None}
# Freed automatically when both peers disconnect.
rooms: dict[int, dict] = {}


# ── Helpers ────────────────────────────────────────────────────────────────

async def send_frame(writer: asyncio.StreamWriter, cmd: int, payload: bytes = b"") -> None:
    """Write a length-prefixed frame and flush."""
    writer.write(bytes([cmd]) + struct.pack("<I", len(payload)) + payload)
    await writer.drain()


async def send_error(writer: asyncio.StreamWriter) -> None:
    writer.write(bytes([ERROR, 0]))
    await writer.drain()


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

            # ── CREATE ────────────────────────────────────────────────────
            if cmd == CREATE:
                if room_code is not None:
                    # Already in a room — reject double-create.
                    await send_error(writer)
                    continue

                room_code  = _unique_room_code()
                is_creator = True
                rooms[room_code] = {"creator": (reader, writer), "joiner": None}

                writer.write(bytes([ROOM_CREATED]) + struct.pack("<I", room_code))
                await writer.drain()
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

                writer.write(bytes([JOIN_OK]))
                await writer.drain()
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
                elif cmd == ANSWER:
                    await send_frame(target_writer, ANSWER_FWD, payload)
                else:
                    await send_frame(target_writer, ICE_FWD, payload)

            else:
                logger.warning("⚠️  Unknown cmd 0x%02x from %s", cmd, peer)
                await send_error(writer)

    except asyncio.IncompleteReadError:
        pass   # peer closed mid-frame
    except ConnectionResetError:
        pass
    except Exception as exc:
        logger.exception("💥 Unexpected error from %s: %s", peer, exc)
    finally:
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
    logger.info("✅ cheery running on %s  [event loop: %s]", addrs, _LOOP)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped")