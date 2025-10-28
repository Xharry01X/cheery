import asyncio
import websockets
import json
import socket

connected_users = {} 

async def notify_all(message):
    """Send a message to all connected clients."""
    if connected_users:
        data = json.dumps(message)
        await asyncio.gather(*(user["ws"].send(data) for user in connected_users.values()))

async def register_user(ws, username, ip):
    connected_users[username] = {"ip": ip, "ws": ws}
    print(f"[+] {username} connected ({ip})")
    await notify_all({
        "type": "user_list",
        "users": list(connected_users.keys())
    })

async def unregister_user(username):
    if username in connected_users:
        print(f"[-] {username} disconnected")
        del connected_users[username]
        await notify_all({
            "type": "user_list",
            "users": list(connected_users.keys())
        })

async def handler(ws):
    username = None
    try:
        async for message in ws:
            data = json.loads(message)
            if data["type"] == "register":
                username = data["username"]
                ip = data["ip"]
                await register_user(ws, username, ip)

            elif data["type"] == "get_ip":
                target = data["target"]
                if target in connected_users:
                    await ws.send(json.dumps({
                        "type": "ip_response",
                        "target": target,
                        "ip": connected_users[target]["ip"]
                    }))
                else:
                    await ws.send(json.dumps({
                        "type": "ip_response",
                        "target": target,
                        "error": "User offline"
                    }))
    except:
        pass
    finally:
        if username:
            await unregister_user(username)

async def main():
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    print("🚀 Central server running on port 8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
