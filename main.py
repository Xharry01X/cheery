import asyncio
import websockets
import json
import time

connected_users = {}

async def notify_all(message):
    """Send message to all connected users"""
    if not connected_users:
        return
        
    data = json.dumps(message)
    dead_users = []
    
    for username, user in connected_users.items():
        try:
            await user["ws"].send(data)
        except:
            dead_users.append(username)
    
    for username in dead_users:
        if username in connected_users:
            print(f"⚡ Removing dead connection: {username}")
            await unregister_user(username)

async def register_user(ws, username, ip):
    """Register a new user"""
    if username in connected_users:
        await ws.send(json.dumps({"type": "error", "message": "Username taken"}))
        return False
        
    connected_users[username] = {
        "ip": ip, 
        "ws": ws, 
        "last_pong": time.time()
    }
    
    print(f"✅ {username} connected from {ip}")
    print(f"👥 Online users: {list(connected_users.keys())}")
    
    await notify_all({
        "type": "user_list", 
        "users": list(connected_users.keys())
    })
    
    return True

async def unregister_user(username):
    """Remove user from connected users"""
    if username in connected_users:
        del connected_users[username]
        print(f"❌ {username} disconnected")
        print(f"👥 Remaining users: {list(connected_users.keys())}")
        
        await notify_all({
            "type": "user_list", 
            "users": list(connected_users.keys())
        })

async def ping_users():
    """Check connection health every 30 seconds"""
    while True:
        await asyncio.sleep(30)
        
        if not connected_users:
            continue
            
        current_time = time.time()
        dead_users = []
        
        for username, user in connected_users.items():
            if current_time - user["last_pong"] > 60:
                dead_users.append(username)
            else:
                try:
                    await user["ws"].send(json.dumps({"type": "ping"}))
                except:
                    dead_users.append(username)
        
        for username in dead_users:
            if username in connected_users:
                print(f"⏰ {username} timed out")
                await unregister_user(username)

async def handler(ws):
    """Handle WebSocket connections"""
    username = None
    client_ip = ws.remote_address[0] if ws.remote_address else "unknown"
    
    try:
        print(f"🔗 New connection from {client_ip}")
        
        async for message in ws:
            try:
                data = json.loads(message)
                
                if data["type"] == "register":
                    username = data["username"]
                    ip = data.get("ip", client_ip)
                    success = await register_user(ws, username, ip)
                    if not success:
                        break

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
                            "error": "User not online"
                        }))
                
                elif data["type"] == "pong":
                    if username and username in connected_users:
                        connected_users[username]["last_pong"] = time.time()
                        
            except json.JSONDecodeError:
                print(f"❓ Invalid JSON from {username or client_ip}")
                
    except websockets.exceptions.ConnectionClosed:
        print(f"📱 Connection closed: {username or client_ip}")
    except Exception as e:
        print(f"💥 Error: {e}")
    finally:
        if username:
            await unregister_user(username)

async def main():
    """Start the server"""
    asyncio.create_task(ping_users())
    
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    
    print("🚀 Central Server Started")
    print("📍 ws://0.0.0.0:8765")
    print("⏰ Auto-ping every 30s, timeout 60s")
    print("Waiting for connections...\n")
    
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())