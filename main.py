import asyncio
import websockets
import uvloop
import time
import json
import logging

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

connected_users = {}
user_index = {}

async def handler(ws):
    logging.info("New connection: %s", ws.remote_address)
    username = None

    try:
        async for message in ws:
            logging.info("Raw message from %s: %s", ws.remote_address, message)

            try:
                data = json.loads(message)
            except Exception as e:
                logging.error("Invalid JSON from %s: %s", ws.remote_address, e)
                continue

            logging.info("Parsed JSON: %s", data)

            op = data.get("t")

            if op == "r":
                username = data["u"]
                connected_users[ws] = {
                    "username": username,
                    "d": data["data"],
                    "ip": time.time(),
                }
                user_index[username] = ws
                logging.info("Registered user '%s'", username)

            elif op == "g":
                target_user = data["u"]
                logging.info("'%s' requested data of '%s'", username, target_user)

                target_ws = user_index.get(target_user)
                if target_ws and target_ws in connected_users:
                    payload = {
                        "t": "i",
                        "d": connected_users[target_ws]["d"],
                    }
                    logging.info("Sending data to '%s': %s", username, payload)
                    await ws.send(json.dumps(payload))
                else:
                    logging.info("Target user '%s' not found or offline", target_user)

            elif op == "p":
                if ws in connected_users:
                    connected_users[ws]["ip"] = time.time()
                    logging.info("Ping received from '%s'", connected_users[ws]["username"])

    except Exception as e:
        logging.error("Exception in handler (%s): %s", ws.remote_address, e)

    finally:
        logging.info("Client disconnected: %s", ws.remote_address)

        if ws in connected_users:
            logging.info("Removing user '%s'", connected_users[ws]["username"])
            del connected_users[ws]

        if username and username in user_index:
            del user_index[username]


async def janitor():
    while True:
        await asyncio.sleep(30)
        if not connected_users:
            continue

        now = time.time()

        dead = [ws for ws, meta in connected_users.items() if now - meta["ip"] > 60]

        for ws in dead:
            logging.warning("Janitor closing inactive user '%s'",
                            connected_users[ws]["username"])
            await ws.close()


async def main():
    asyncio.create_task(janitor())

    async with websockets.serve(handler, "0.0.0.0", 8765):
        logging.info("WebSocket Server Running on :8765")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped by user")
