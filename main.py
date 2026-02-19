import json
import logging
import queue
import signal
import socket
import sys
import threading

logging.basicConfig(
    format="[%(threadName)s] %(levelname)s: %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

HOST, PORT = "0.0.0.0", 8765
BUFFER_SIZE = 4096



def send_json(sock, payload):
    try:
        sock.sendall((json.dumps(payload) + "\n").encode())
        return True
    except OSError:
        return False


def broadcast(queues, payload):
    for q in queues:
        try:
            q.put_nowait(payload)
        except Exception:
            pass


def user_list_payload(connected_users):
    return {"type": "user_list", "users": list(connected_users.keys())}



def handle_client(client_sock, addr, connected_users, lock, inbox, all_queues):
    client_sock.settimeout(1.0)
    username = None
    buf = b""

    try:
        while True:
            try:
                while True:
                    send_json(client_sock, inbox.get_nowait())
            except Exception:
                pass

            try:
                chunk = client_sock.recv(BUFFER_SIZE)
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                continue
            except OSError:
                break

            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning(f"Malformed JSON from {addr}")
                    continue

                mtype = data.get("type")

                if mtype == "register":
                    username = data["username"]
                    with lock:
                        connected_users[username] = {"ip": data["ip"], "addr": addr}
                    log.info(f"✅ '{username}' registered from {data['ip']}")
                    broadcast(all_queues, user_list_payload(connected_users))

                elif mtype == "heartbeat":
                    send_json(client_sock, {"type": "heartbeat_ack"})

                elif mtype == "get_ip":
                    target = data.get("target")
                    entry = connected_users.get(target)
                    send_json(
                        client_sock,
                        {
                            "type": "ip_response",
                            "target": target,
                            **(
                                {"ip": entry["ip"]}
                                if entry
                                else {"error": "User offline"}
                            ),
                        },
                    )

                elif mtype == "message":
                    broadcast(
                        all_queues,
                        {
                            "type": "message",
                            "from": username,
                            "content": data.get("content"),
                        },
                    )

    finally:
        if username and username in connected_users:
            with lock:
                connected_users.pop(username, None)
            log.info(f"❌ '{username}' disconnected")
            broadcast(all_queues, user_list_payload(connected_users))
        client_sock.close()




def main():
    signal.signal(signal.SIGINT, lambda *_: (log.info("Shutting down..."), sys.exit(0)))

    connected_users = {}
    users_lock = threading.Lock()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(100)

    log.info(f"🚀 Server on {HOST}:{PORT} | Threads available")

    threads, queues = [], []

    try:
        while True:
            client_sock, addr = server.accept()
            threads = [t for t in threads if t.is_alive()]

            inbox = queue.Queue()
            queues.append(inbox)

            thread = threading.Thread(
                target=handle_client,
                args=(
                    client_sock,
                    addr,
                    connected_users,
                    users_lock,
                    inbox,
                    queues,
                ),
                daemon=True,
            )
            thread.start()
            threads.append(thread)
            log.info(
                f"🔌 New connection from {addr} → Thread {thread.name} | Active: {len(threads)}"
            )

    finally:
        for t in threads:
            t.join(timeout=1.0)
        server.close()


if __name__ == "__main__":
    main()
