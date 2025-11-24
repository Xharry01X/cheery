import asyncio
import struct
import logging
from dataclasses import dataclass
from typing import Optional, Dict

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

PORT = 8765
TIMEOUT = 60  

CMD_CREATE = 0x01
CMD_JOIN   = 0x02
RESP_ACK   = 0x01
RESP_MATCH = 0x04
RESP_ERR   = 0x05  


@dataclass
class Client:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    ip: str
    port: int
    timeout_handle: Optional[asyncio.TimerHandle] = None


class SignalingServer:
    def __init__(self, host: str = "0.0.0.0", port: int = PORT):
        self.host = host
        self.port = port
        # Only state: code -> creator client
        self.rooms: Dict[int, Client] = {}
        self.loop = asyncio.get_event_loop()

    async def send_bytes(self, client: Client, data: bytes) -> bool:
        try:
            client.writer.write(data)
            await client.writer.drain()
            return True
        except Exception:
            return False

    async def close_client(self, client: Client) -> None:
        try:
            client.writer.close()
            await client.writer.wait_closed()
        except Exception:
            pass

    def schedule_timeout(self, code: int, client: Client) -> None:
        # Cancel old timeout if any
        if client.timeout_handle and not client.timeout_handle.cancelled():
            client.timeout_handle.cancel()

        def on_timeout():
            # Runs in event loop thread
            if self.rooms.get(code) is client:
                logger.info(f"Room timeout code={code} from {client.ip}:{client.port}")
                self.rooms.pop(code, None)
                asyncio.create_task(self.close_client(client))

        client.timeout_handle = self.loop.call_later(TIMEOUT, on_timeout)

    async def handle_create(self, client: Client, code: int) -> None:
        # If code already in use, reject
        if code in self.rooms:
            await self.send_bytes(client, bytes([RESP_ERR]))
            return

        self.rooms[code] = client
        self.schedule_timeout(code, client)
        ok = await self.send_bytes(client, bytes([RESP_ACK]))
        if not ok:
            # Creator vanished immediately; clean state
            self.rooms.pop(code, None)
            return

        logger.info(f"Room created code={code} by {client.ip}:{client.port}")

    async def handle_join(self, joiner: Client, code: int) -> None:
        creator = self.rooms.pop(code, None)
        if not creator:
            # No such room
            await self.send_bytes(joiner, bytes([RESP_ERR]))
            return

        # Cancel creator timeout
        if creator.timeout_handle and not creator.timeout_handle.cancelled():
            creator.timeout_handle.cancel()
            creator.timeout_handle = None

        # Build "MATCH" responses: [RESP_MATCH][ip]\x00[port_le]
        def build_match(ip: str, port: int) -> bytes:
            b = bytearray()
            b.append(RESP_MATCH)
            ip_bytes = ip.encode("utf-8")[:255]
            b.extend(ip_bytes)
            b.append(0x00)
            b.extend(struct.pack("<H", port))
            return bytes(b)

        to_joiner = build_match(creator.ip, creator.port)
        to_creator = build_match(joiner.ip, joiner.port)

        ok_creator = await self.send_bytes(creator, to_creator)
        ok_joiner = await self.send_bytes(joiner, to_joiner)

        logger.info(
            f"Matched code={code}: "
            f"{creator.ip}:{creator.port} <-> {joiner.ip}:{joiner.port}"
        )
        await self.close_client(creator)
        await self.close_client(joiner)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        if not peer or len(peer) < 2:
            ip, port = "0.0.0.0", 0
        else:
            ip, port = peer[0], peer[1]

        client = Client(reader=reader, writer=writer, ip=ip, port=port)
        logger.debug(f"Client connected {ip}:{port}")

        try:
            while True:
                try:
                    cmd_bytes = await asyncio.wait_for(reader.readexactly(1), timeout=TIMEOUT)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                if not cmd_bytes:
                    break

                cmd = cmd_bytes[0]
                try:
                    code_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=5)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                code = struct.unpack("<I", code_bytes)[0]

                if cmd == CMD_CREATE:
                    await self.handle_create(client, code)
                elif cmd == CMD_JOIN:
                    await self.handle_join(client, code)
                    return
                else:
                    await self.send_bytes(client, bytes([RESP_ERR]))
                    break

        finally:
            await self.close_client(client)
            logger.debug(f"Client disconnected {ip}:{port}")

    async def run(self) -> None:
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info(f"Signaling server listening on {self.host}:{self.port}")
        async with server:
            await server.serve_forever()


async def main():
    srv = SignalingServer()
    await srv.run()


if __name__ == "__main__":
    asyncio.run(main())
