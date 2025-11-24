import asyncio
import struct
import random

# Commands
CREATE = 0x01
JOIN   = 0x02
OFFER  = 0x03
ANSWER = 0x04
ICE    = 0x05

# Responses
ROOM_CREATED = 0x10
JOIN_OK      = 0x11
OFFER_FWD    = 0x20
ANSWER_FWD   = 0x21
ICE_FWD      = 0x22
ERROR        = 0x7F

rooms = {}  # code -> (creator, joiner)

async def send_frame(writer, cmd, payload=b""):
    writer.write(bytes([cmd]) + struct.pack("<I", len(payload)) + payload)
    await writer.drain()

async def send_error(writer):
    writer.write(bytes([ERROR, 1]))
    await writer.drain()

async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    client = (reader, writer)
    room_code = None
    is_creator = False

    try:
        while True:
            cmd_byte = await reader.read(1)
            if not cmd_byte:
                break
            cmd = cmd_byte[0]

            # CREATE ROOM
            if cmd == CREATE:
                room_code = random.randint(100000, 999999)
                rooms[room_code] = {"creator": client, "joiner": None}
                is_creator = True
                writer.write(bytes([ROOM_CREATED]) + struct.pack("<I", room_code))
                await writer.drain()

            # JOIN ROOM
            elif cmd == JOIN:
                code_bytes = await reader.readexactly(4)
                code = struct.unpack("<I", code_bytes)[0]

                if code not in rooms or rooms[code]["joiner"]:
                    await send_error(writer)
                    continue

                rooms[code]["joiner"] = client
                room_code = code
                writer.write(bytes([JOIN_OK]))
                await writer.drain()

            # OFFER / ANSWER / ICE
            elif cmd in (OFFER, ANSWER, ICE):
                len_bytes = await reader.readexactly(4)
                size = struct.unpack("<I", len_bytes)[0]
                payload = await reader.readexactly(size)

                if room_code not in rooms:
                    await send_error(writer)
                    continue

                room = rooms[room_code]
                creator = room["creator"]
                joiner = room["joiner"]

                # Forward to the other peer
                target = joiner if is_creator else creator
                if not target:
                    continue

                _, w = target

                if cmd == OFFER:
                    await send_frame(w, OFFER_FWD, payload)
                elif cmd == ANSWER:
                    await send_frame(w, ANSWER_FWD, payload)
                else:
                    await send_frame(w, ICE_FWD, payload)

            # Unknown
            else:
                await send_error(writer)

    except:
        pass
    finally:
        # cleanup
        if room_code in rooms:
            rooms.pop(room_code, None)
        writer.close()
        await writer.wait_closed()

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8765)
    async with server:
        await server.serve_forever()

asyncio.run(main())
