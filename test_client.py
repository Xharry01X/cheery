import json
import socket
import time

HOST, PORT = "localhost", 8765


def send_message(sock, message):
    """Send a JSON message to the server."""
    try:
        sock.sendall((json.dumps(message) + "\n").encode())
        print(f"📤 Sent: {message}")
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        return False
    return True


def receive_message(sock, timeout=2.0):
    """Receive a JSON message from the server."""
    sock.settimeout(timeout)
    try:
        data = sock.recv(4096).decode()
        if not data:
            return None

        # Split by newlines and process each message
        messages = data.strip().split("\n")
        results = []
        for msg in messages:
            try:
                results.append(json.loads(msg))
                print(f"📥 Received: {results[-1]}")
            except json.JSONDecodeError:
                print(f"⚠️  Non-JSON message: {msg}")

        return results
    except socket.timeout:
        print("⏱️  Timeout waiting for response")
        return None
    except Exception as e:
        print(f"❌ Error receiving message: {e}")
        return None


def test_server():
    """Test the server with various message types."""
    print(f"🔌 Connecting to {HOST}:{PORT}...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((HOST, PORT))
        print("✅ Connected successfully!\n")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return

    try:
        # Test 1: Register a user
        print("=" * 50)
        print("Test 1: Registering user 'alice'")
        print("=" * 50)
        send_message(
            sock, {"type": "register", "username": "alice", "ip": "192.168.1.100"}
        )
        time.sleep(0.5)
        receive_message(sock)
        time.sleep(1)

        # Test 2: Heartbeat
        print("\n" + "=" * 50)
        print("Test 2: Sending heartbeat")
        print("=" * 50)
        send_message(sock, {"type": "heartbeat"})
        time.sleep(0.5)
        receive_message(sock)
        time.sleep(1)

        # Test 3: Get IP of non-existent user
        print("\n" + "=" * 50)
        print("Test 3: Getting IP of non-existent user 'bob'")
        print("=" * 50)
        send_message(sock, {"type": "get_ip", "target": "bob"})
        time.sleep(0.5)
        receive_message(sock)
        time.sleep(1)

        # Test 4: Send a message
        print("\n" + "=" * 50)
        print("Test 4: Broadcasting a message")
        print("=" * 50)
        send_message(sock, {"type": "message", "content": "Hello from alice!"})
        time.sleep(0.5)
        receive_message(sock)
        time.sleep(1)

        # Test 5: Multiple quick messages
        print("\n" + "=" * 50)
        print("Test 5: Sending multiple quick messages")
        print("=" * 50)
        for i in range(3):
            send_message(sock, {"type": "heartbeat"})
        time.sleep(0.5)
        receive_message(sock)
        time.sleep(1)

    finally:
        print("\n" + "=" * 50)
        print("Closing connection")
        print("=" * 50)
        sock.close()
        print("✅ Test client finished")


if __name__ == "__main__":
    test_server()
