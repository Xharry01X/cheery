# Cheery - WebSocket Relay Server

A minimal, central WebSocket relay server designed to facilitate peer-to-peer connections between clients. This server acts as a signaling server to help clients discover each other and establish direct connections.

## Features

- 📡 Real-time user presence tracking
- 🔄 Automatic user list updates for all connected clients
- 🌐 IP address exchange for peer-to-peer connections
- 🚀 Built with Python's asyncio and websockets for high performance
- 🔒 Simple and lightweight implementation

## Prerequisites

- Python 3.9 or higher
- Poetry (for dependency management)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/cheery.git
   cd cheery
   ```

2. Install dependencies using Poetry:
   ```bash
   poetry install
   ```

## Usage

1. Start the server:
   ```bash
   poetry run python main.py
   ```

2. The server will start on `ws://0.0.0.0:8765`

## API Reference

### Register a User
```json
{
    "type": "register",
    "username": "your_username",
    "ip": "your_ip_address"
}
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
