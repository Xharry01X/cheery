# Cheery - Minimal Relay Server

A high-performance relay server designed to facilitate peer-to-peer connections between clients using a simple binary protocol.

## Features

- 🚀 Ultra-fast C implementation using epoll
- 🔄 Simple binary protocol
- ⏱️ Automatic connection timeouts
- 🔒 No external dependencies
- 💻 Cross-platform (Linux/Unix)

## Build & Run

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/cheery.git
   cd cheery
   ```

2. Build the server:
   ```bash
   make
   ```

3. Run the server:
   ```bash
   ./build/main
   ```

The server will listen on `0.0.0.0:8765` by default.

## Binary Protocol

### Packet Structure
All packets start with a 1-byte command followed by optional payload.

### Commands

#### 0x01 - Create Room
Create a new room with a 4-byte room code.
```
[0x01][code:4]
```

#### 0x02 - Join Room
Join an existing room with a 4-byte room code.
```
[0x02][code:4]
```

Responses:
- `0x04` - Matched with peer
- `0x05` - Waiting for peer

#### 0x03 - Relay Data
Send data to the paired peer.
```
[0x03][data...]
```

### Get User IP
```json
{
    "type": "get_ip",
    "target": "username_to_query"
}
```

### Server Responses
- **User List Update** (sent to all clients when user list changes):
  ```json
  {
      "type": "user_list",
      "users": ["user1", "user2"]
  }
  ```

- **IP Response** (response to get_ip request):
  ```json
  {
      "type": "ip_response",
      "target": "queried_username",
      "ip": "192.168.1.100"
  }
  ```
  or if user is not found:
  ```json
  {
      "type": "ip_response",
      "target": "nonexistent_user",
      "error": "User offline"
  }
  ```

## Project Structure

- `main.py` - Main server implementation
- `pyproject.toml` - Project configuration and dependencies
- `poetry.lock` - Lock file for reproducible builds

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
