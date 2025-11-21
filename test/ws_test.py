import asyncio
import websockets
import json

async def test():
    async with websockets.connect("ws://192.168.1.16:8765") as ws:
        await ws.send(json.dumps({"t":"r","u":"harry","data":{"x":1}}))
        print(await ws.recv())

asyncio.run(test())
