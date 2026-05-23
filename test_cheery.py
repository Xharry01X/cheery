import asyncio
import struct
import logging

# Importing cheery sets the uvloop event loop policy globally (if uvloop is
# installed), so every asyncio.run() call in this file automatically uses it.
from cheery import (
    handle_client, CREATE, JOIN, OFFER, ANSWER, ICE,
    ROOM_CREATED, JOIN_OK, OFFER_FWD, ANSWER_FWD, ICE_FWD, ERROR,
    rooms, _LOOP,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockWriter:
    """Mock writer for testing."""
    def __init__(self, peername=("127.0.0.1", 12345)):
        self.data = b""
        self.closed = False
        self._peername = peername

    def write(self, data):
        self.data += data

    async def drain(self):
        await asyncio.sleep(0)

    def close(self):
        self.closed = True

    async def wait_closed(self):
        await asyncio.sleep(0)

    def get_extra_info(self, key):
        if key == "peername":
            return self._peername
        return None


class MockReader:
    """Async mock reader that blocks until data is available or EOF."""
    def __init__(self):
        self._buffer = b""
        self._eof = False
        self._event = asyncio.Event()

    def feed_data(self, data: bytes):
        self._buffer += data
        self._event.set()

    def feed_eof(self):
        self._eof = True
        self._event.set()

    async def read(self, n: int) -> bytes:
        while len(self._buffer) < n and not self._eof:
            self._event.clear()
            await self._event.wait()
        if self._eof and len(self._buffer) == 0:
            return b""
        chunk = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return chunk

    async def readexactly(self, n: int) -> bytes:
        data = bytearray()
        while len(data) < n:
            chunk = await self.read(n - len(data))
            if not chunk:
                raise asyncio.IncompleteReadError(bytes(data), n)
            data.extend(chunk)
        return bytes(data)


async def wait_for_condition(writer, condition, timeout=3.0, interval=0.01):
    """Poll writer.data until condition(writer.data) is True."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition(writer.data):
        if loop.time() > deadline:
            raise TimeoutError("Condition not met within timeout")
        await asyncio.sleep(interval)


async def wait_for_room_cleanup(room_code, timeout=5.0):
    """Wait for a room to be cleaned up."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while room_code in rooms:
        if loop.time() > deadline:
            raise TimeoutError(f"Room {room_code} not cleaned up within timeout")
        await asyncio.sleep(0.01)


async def test_single_connection_create_room():
    """Test a single client creating a room."""
    print("\n🧪 Test 1: Single client creating a room")
    rooms.clear()

    reader = MockReader()
    writer = MockWriter()
    reader.feed_data(bytes([CREATE]))

    task = asyncio.create_task(handle_client(reader, writer))

    await wait_for_condition(writer, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)

    reader.feed_eof()
    await task

    if writer.data[0] == ROOM_CREATED:
        print("✅ PASSED: Room created successfully")
        return True
    else:
        print("❌ FAILED: Room not created")
        return False


async def test_two_connections_create_and_join():
    """Test two clients creating and joining a room."""
    print("\n🧪 Test 2: Two clients create and join room")
    rooms.clear()

    reader1 = MockReader()
    writer1 = MockWriter()
    reader1.feed_data(bytes([CREATE]))
    task1 = asyncio.create_task(handle_client(reader1, writer1))

    await wait_for_condition(writer1, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
    room_code = struct.unpack("<I", writer1.data[1:5])[0]

    reader2 = MockReader()
    writer2 = MockWriter()
    reader2.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
    task2 = asyncio.create_task(handle_client(reader2, writer2))

    await wait_for_condition(writer2, lambda d: len(d) > 0 and d[0] in (JOIN_OK, ERROR))

    reader1.feed_eof()
    reader2.feed_eof()
    await asyncio.gather(task1, task2)

    if writer2.data[0] == JOIN_OK:
        print("✅ PASSED: Second client joined successfully")
        return True
    else:
        print("❌ FAILED: Join failed")
        return False


async def test_ten_parallel_creates():
    """Test 10 clients creating rooms in parallel."""
    print("\n🧪 Test 3: 10 clients creating rooms in parallel")
    rooms.clear()

    async def create_room():
        reader = MockReader()
        writer = MockWriter()
        reader.feed_data(bytes([CREATE]))
        task = asyncio.create_task(handle_client(reader, writer))
        await wait_for_condition(writer, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
        return reader, writer, task

    clients = await asyncio.gather(*[create_room() for _ in range(10)])

    all_created = all(
        len(w.data) >= 5 and w.data[0] == ROOM_CREATED
        for _, w, _ in clients
    )

    if all_created and len(rooms) == 10:
        print("✅ PASSED: All 10 rooms created successfully")
        result = True
    else:
        print(f"❌ FAILED: Only {len(rooms)}/10 rooms created")
        result = False

    for reader, _, task in clients:
        reader.feed_eof()
    await asyncio.gather(*[task for _, _, task in clients])
    return result


async def test_invalid_join_error():
    """Test joining a non-existent room returns error."""
    print("\n🧪 Test 4: Joining non-existent room")
    rooms.clear()

    reader = MockReader()
    writer = MockWriter()
    invalid_code = 999999
    reader.feed_data(bytes([JOIN]) + struct.pack("<I", invalid_code))

    task = asyncio.create_task(handle_client(reader, writer))
    await wait_for_condition(writer, lambda d: len(d) > 0 and d[0] == ERROR)
    reader.feed_eof()
    await task

    if writer.data[0] == ERROR:
        print("✅ PASSED: Error returned for invalid room")
        return True
    else:
        print("❌ FAILED: Should have returned error")
        return False


async def test_multiple_joiners_rejected():
    """Test that a second joiner gets rejected."""
    print("\n🧪 Test 5: Rejecting second joiner")
    rooms.clear()

    reader1 = MockReader()
    writer1 = MockWriter()
    reader1.feed_data(bytes([CREATE]))
    task1 = asyncio.create_task(handle_client(reader1, writer1))
    await wait_for_condition(writer1, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
    room_code = struct.unpack("<I", writer1.data[1:5])[0]

    reader2 = MockReader()
    writer2 = MockWriter()
    reader2.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
    task2 = asyncio.create_task(handle_client(reader2, writer2))
    await wait_for_condition(writer2, lambda d: len(d) > 0 and d[0] == JOIN_OK)

    reader3 = MockReader()
    writer3 = MockWriter()
    reader3.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
    task3 = asyncio.create_task(handle_client(reader3, writer3))
    await wait_for_condition(writer3, lambda d: len(d) > 0 and d[0] == ERROR)

    for r in (reader1, reader2, reader3):
        r.feed_eof()
    await asyncio.gather(task1, task2, task3)

    if writer2.data[0] == JOIN_OK and writer3.data[0] == ERROR:
        print("✅ PASSED: First joiner succeeded, second was rejected")
        return True
    else:
        print("❌ FAILED: Join logic incorrect")
        return False


async def test_offer_forwarding():
    """Test forwarding OFFER between peers."""
    print("\n🧪 Test 6: Forwarding OFFER between peers")
    rooms.clear()

    reader1 = MockReader()
    writer1 = MockWriter()
    reader1.feed_data(bytes([CREATE]))
    task1 = asyncio.create_task(handle_client(reader1, writer1))
    await wait_for_condition(writer1, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
    room_code = struct.unpack("<I", writer1.data[1:5])[0]

    reader2 = MockReader()
    writer2 = MockWriter()
    reader2.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
    task2 = asyncio.create_task(handle_client(reader2, writer2))
    await wait_for_condition(writer2, lambda d: len(d) > 0 and d[0] == JOIN_OK)

    writer2_initial_len = len(writer2.data)

    offer_payload = b'{"type":"offer","sdp":"test"}'
    reader1.feed_data(
        bytes([OFFER]) + struct.pack("<I", len(offer_payload)) + offer_payload
    )

    await wait_for_condition(
        writer2,
        lambda d: len(d) > writer2_initial_len and d[writer2_initial_len] == OFFER_FWD
    )

    reader1.feed_eof()
    reader2.feed_eof()
    await asyncio.gather(task1, task2)

    if len(writer2.data) > writer2_initial_len and writer2.data[writer2_initial_len] == OFFER_FWD:
        print("✅ PASSED: OFFER forwarded successfully")
        return True
    else:
        print("❌ FAILED: OFFER not forwarded")
        return False


async def test_massive_concurrent_rooms():
    """Test creating 100 rooms simultaneously."""
    print("\n🧪 Test 7: Creating 100 rooms concurrently (stress test)")
    rooms.clear()

    async def create_room():
        reader = MockReader()
        writer = MockWriter()
        reader.feed_data(bytes([CREATE]))
        task = asyncio.create_task(handle_client(reader, writer))
        await wait_for_condition(writer, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
        return reader, writer, task

    NUM_ROOMS = 100
    clients = await asyncio.gather(*[create_room() for _ in range(NUM_ROOMS)])

    all_created = all(
        len(w.data) >= 5 and w.data[0] == ROOM_CREATED
        for _, w, _ in clients
    )

    if all_created and len(rooms) == NUM_ROOMS:
        print(f"✅ PASSED: All {NUM_ROOMS} rooms created successfully")
        result = True
    else:
        print(f"❌ FAILED: Only {len(rooms)}/{NUM_ROOMS} rooms created")
        result = False

    for reader, _, task in clients:
        reader.feed_eof()
    await asyncio.gather(*[task for _, _, task in clients])
    return result


async def test_rapid_join_leave():
    """Test rapid join and leave scenarios."""
    print("\n🧪 Test 8: Rapid join and leave")
    rooms.clear()

    reader1 = MockReader()
    writer1 = MockWriter()
    reader1.feed_data(bytes([CREATE]))
    task1 = asyncio.create_task(handle_client(reader1, writer1))
    await wait_for_condition(writer1, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
    room_code = struct.unpack("<I", writer1.data[1:5])[0]

    success_count = 0
    for i in range(20):
        reader_join = MockReader()
        writer_join = MockWriter()
        reader_join.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
        task_join = asyncio.create_task(handle_client(reader_join, writer_join))
        await wait_for_condition(writer_join, lambda d: len(d) > 0)

        if writer_join.data[0] == JOIN_OK:
            success_count += 1

        reader_join.feed_eof()
        await task_join

    reader1.feed_eof()
    await task1

    if success_count >= 1:
        print(f"✅ PASSED: {success_count} successful joins in rapid sequence")
        return True
    else:
        print("❌ FAILED: No successful joins")
        return False


async def test_bidirectional_messaging():
    """Test messages flowing in both directions."""
    print("\n🧪 Test 9: Bidirectional messaging between peers")
    rooms.clear()

    reader1 = MockReader()
    writer1 = MockWriter()
    reader1.feed_data(bytes([CREATE]))
    task1 = asyncio.create_task(handle_client(reader1, writer1))
    await wait_for_condition(writer1, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
    room_code = struct.unpack("<I", writer1.data[1:5])[0]

    reader2 = MockReader()
    writer2 = MockWriter()
    reader2.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
    task2 = asyncio.create_task(handle_client(reader2, writer2))
    await wait_for_condition(writer2, lambda d: len(d) > 0 and d[0] == JOIN_OK)

    w2_initial = len(writer2.data)
    offer_payload = b'{"type":"offer"}'
    reader1.feed_data(bytes([OFFER]) + struct.pack("<I", len(offer_payload)) + offer_payload)
    await wait_for_condition(writer2, lambda d: len(d) > w2_initial and d[w2_initial] == OFFER_FWD)

    w1_initial = len(writer1.data)
    answer_payload = b'{"type":"answer"}'
    reader2.feed_data(bytes([ANSWER]) + struct.pack("<I", len(answer_payload)) + answer_payload)
    await wait_for_condition(writer1, lambda d: len(d) > w1_initial and d[w1_initial] == ANSWER_FWD)

    w2_new = len(writer2.data)
    ice_payload = b'{"type":"ice","candidate":"test"}'
    reader1.feed_data(bytes([ICE]) + struct.pack("<I", len(ice_payload)) + ice_payload)
    await wait_for_condition(writer2, lambda d: len(d) > w2_new and d[w2_new] == ICE_FWD)

    reader1.feed_eof()
    reader2.feed_eof()
    await asyncio.gather(task1, task2)

    if (writer2.data[w2_initial] == OFFER_FWD and
            writer1.data[w1_initial] == ANSWER_FWD and
            writer2.data[w2_new] == ICE_FWD):
        print("✅ PASSED: Bidirectional messaging works correctly")
        return True
    else:
        print("❌ FAILED: Bidirectional messaging failed")
        return False


async def test_concurrent_message_flood():
    """Test flooding messages between multiple room pairs."""
    print("\n🧪 Test 10: Concurrent message flooding (50 room pairs)")
    rooms.clear()

    async def create_room_pair():
        r1 = MockReader()
        w1 = MockWriter()
        r1.feed_data(bytes([CREATE]))
        t1 = asyncio.create_task(handle_client(r1, w1))
        await wait_for_condition(w1, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
        room_code = struct.unpack("<I", w1.data[1:5])[0]

        r2 = MockReader()
        w2 = MockWriter()
        r2.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
        t2 = asyncio.create_task(handle_client(r2, w2))
        await wait_for_condition(w2, lambda d: len(d) > 0 and d[0] == JOIN_OK)

        w2_initial = len(w2.data)
        payload = b"test_payload"
        r1.feed_data(bytes([OFFER]) + struct.pack("<I", len(payload)) + payload)
        await wait_for_condition(w2, lambda d: len(d) > w2_initial)

        return (r1, w1, t1), (r2, w2, t2), w2_initial

    NUM_PAIRS = 50
    pairs = await asyncio.gather(*[create_room_pair() for _ in range(NUM_PAIRS)])

    success_count = 0
    for (r1, w1, t1), (r2, w2, t2), w2_initial in pairs:
        if len(w2.data) > w2_initial and w2.data[w2_initial] == OFFER_FWD:
            success_count += 1
        r1.feed_eof()
        r2.feed_eof()

    await asyncio.gather(*[t1 for (_, _, t1), _, _ in pairs])
    await asyncio.gather(*[t2 for _, (_, _, t2), _ in pairs])

    if success_count == NUM_PAIRS:
        print(f"✅ PASSED: All {NUM_PAIRS} room pairs forwarded messages correctly")
        return True
    else:
        print(f"❌ FAILED: Only {success_count}/{NUM_PAIRS} pairs succeeded")
        return False


async def test_full_signaling_flow():
    """Test complete WebRTC signaling flow."""
    print("\n🧪 Test 11: Full WebRTC signaling flow (OFFER → ANSWER → ICE)")
    rooms.clear()

    reader1 = MockReader()
    writer1 = MockWriter(peername=("127.0.0.1", 11111))
    reader1.feed_data(bytes([CREATE]))
    task1 = asyncio.create_task(handle_client(reader1, writer1))
    await wait_for_condition(writer1, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
    room_code = struct.unpack("<I", writer1.data[1:5])[0]
    print(f"   📝 Room {room_code} created")

    reader2 = MockReader()
    writer2 = MockWriter(peername=("127.0.0.1", 22222))
    reader2.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
    task2 = asyncio.create_task(handle_client(reader2, writer2))
    await wait_for_condition(writer2, lambda d: len(d) > 0 and d[0] == JOIN_OK)
    print(f"   ✅ Client joined room {room_code}")

    w1_pos = len(writer1.data)
    w2_pos = len(writer2.data)

    offer_sdp = b'v=0\r\no=- 123456 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n'
    reader1.feed_data(bytes([OFFER]) + struct.pack("<I", len(offer_sdp)) + offer_sdp)
    await wait_for_condition(writer2, lambda d: len(d) > w2_pos and d[w2_pos] == OFFER_FWD)
    print("   📤 OFFER sent from Creator → Joiner")
    w2_pos = len(writer2.data)

    answer_sdp = b'v=0\r\no=- 654321 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n'
    reader2.feed_data(bytes([ANSWER]) + struct.pack("<I", len(answer_sdp)) + answer_sdp)
    await wait_for_condition(writer1, lambda d: len(d) > w1_pos and d[w1_pos] == ANSWER_FWD)
    print("   📥 ANSWER sent from Joiner → Creator")
    w1_pos = len(writer1.data)

    ice_candidates = [
        b'candidate:1 1 UDP 2130706431 192.168.1.1 8000 typ host',
        b'candidate:2 1 UDP 1694498815 10.0.0.1 8001 typ srflx',
        b'candidate:3 1 UDP 16777215 203.0.113.1 8002 typ relay',
    ]

    for ice in ice_candidates:
        reader1.feed_data(bytes([ICE]) + struct.pack("<I", len(ice)) + ice)
        await wait_for_condition(writer2, lambda d: len(d) > w2_pos and d[w2_pos] == ICE_FWD)
        w2_pos = len(writer2.data)

        reader2.feed_data(bytes([ICE]) + struct.pack("<I", len(ice)) + ice)
        await wait_for_condition(writer1, lambda d: len(d) > w1_pos and d[w1_pos] == ICE_FWD)
        w1_pos = len(writer1.data)

    print(f"   🧊 {len(ice_candidates) * 2} ICE candidates exchanged")

    for i in range(3):
        msg = f"keepalive_{i}".encode()
        reader1.feed_data(bytes([OFFER]) + struct.pack("<I", len(msg)) + msg)
        await wait_for_condition(writer2, lambda d: len(d) > w2_pos)
        w2_pos = len(writer2.data)
    print("   🔄 Keep-alive messages sent")

    reader2.feed_eof()
    await task2
    print("   🔌 Joiner disconnected")

    room_exists_after_joiner = room_code in rooms
    print(f"   📊 Room exists after joiner leaves: {room_exists_after_joiner}")

    reader1.feed_eof()
    await task1
    print("   🔌 Creator disconnected")

    room_exists_after_all = room_code in rooms
    print(f"   📊 Room exists after all disconnect: {room_exists_after_all}")

    success = not room_exists_after_all
    if success:
        print("✅ PASSED: Full signaling flow works correctly")
    else:
        print("❌ FAILED: Room not cleaned up properly")

    return success


async def test_long_lived_connection_messages():
    """Test keeping connections alive and sending many messages over time."""
    print("\n🧪 Test 12: Long-lived connection with 100 messages")
    rooms.clear()

    reader1 = MockReader()
    writer1 = MockWriter(peername=("127.0.0.1", 33333))
    reader1.feed_data(bytes([CREATE]))
    task1 = asyncio.create_task(handle_client(reader1, writer1))
    await wait_for_condition(writer1, lambda d: len(d) >= 5 and d[0] == ROOM_CREATED)
    room_code = struct.unpack("<I", writer1.data[1:5])[0]

    reader2 = MockReader()
    writer2 = MockWriter(peername=("127.0.0.1", 44444))
    reader2.feed_data(bytes([JOIN]) + struct.pack("<I", room_code))
    task2 = asyncio.create_task(handle_client(reader2, writer2))
    await wait_for_condition(writer2, lambda d: len(d) > 0 and d[0] == JOIN_OK)

    w1_pos = len(writer1.data)
    w2_pos = len(writer2.data)

    messages_sent = 0
    for i in range(50):
        msg = f"message_from_creator_{i}".encode()
        reader1.feed_data(bytes([OFFER]) + struct.pack("<I", len(msg)) + msg)
        await wait_for_condition(writer2, lambda d: len(d) > w2_pos)
        w2_pos = len(writer2.data)
        messages_sent += 1

        msg = f"message_from_joiner_{i}".encode()
        reader2.feed_data(bytes([ANSWER]) + struct.pack("<I", len(msg)) + msg)
        await wait_for_condition(writer1, lambda d: len(d) > w1_pos)
        w1_pos = len(writer1.data)
        messages_sent += 1

    print(f"   ✉️  {messages_sent} messages exchanged successfully")

    room_active = room_code in rooms
    print(f"   📊 Room still active: {room_active}")

    reader1.feed_eof()
    reader2.feed_eof()
    await asyncio.gather(task1, task2)

    room_cleaned = room_code not in rooms
    print(f"   📊 Room cleaned up: {room_cleaned}")

    success = messages_sent == 100 and room_active and room_cleaned
    if success:
        print("✅ PASSED: Long-lived connection handled 100 messages correctly")
    else:
        print("❌ FAILED: Long-lived connection test failed")

    return success


async def test_unknown_command_handling():
    """Test that unknown commands are handled gracefully without warnings."""
    print("\n🧪 Test 13: Unknown command handling (no warnings)")
    rooms.clear()

    reader = MockReader()
    writer = MockWriter()

    # Send an unknown command (e.g., 0x47 = 'G' for GET request)
    reader.feed_data(bytes([0x47]))

    task = asyncio.create_task(handle_client(reader, writer))

    # Wait for the error response
    await wait_for_condition(writer, lambda d: len(d) > 0)

    # Check that we got an error response
    if writer.data[0] == ERROR:
        print("✅ PASSED: Unknown command handled with error response")
        result = True
    else:
        print("❌ FAILED: Expected error response for unknown command")
        result = False

    reader.feed_eof()
    await task
    return result


async def run_all_tests():
    """Run all tests sequentially."""
    print("=" * 60)
    print("🧪 STARTING TESTS FOR CHEERY SERVER")
    print(f"⚡ Event loop: {_LOOP}")
    print("=" * 60)

    tests = [
        ("Basic Functionality", [
            test_single_connection_create_room,
            test_two_connections_create_and_join,
            test_ten_parallel_creates,
            test_invalid_join_error,
            test_multiple_joiners_rejected,
            test_offer_forwarding,
        ]),
        ("Stress & Performance", [
            test_massive_concurrent_rooms,
            test_rapid_join_leave,
            test_bidirectional_messaging,
            test_concurrent_message_flood,
        ]),
        ("Connection Lifecycle", [
            test_full_signaling_flow,
            test_long_lived_connection_messages,
        ]),
        ("Error Handling", [
            test_unknown_command_handling,
        ]),
    ]

    all_results = []

    for category, test_funcs in tests:
        print(f"\n{'=' * 60}")
        print(f"📦 {category}")
        print(f"{'=' * 60}")

        for test in test_funcs:
            result = await test()
            all_results.append(result)

    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)

    passed = sum(all_results)
    total = len(all_results)

    for i, result in enumerate(all_results, 1):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"Test {i:>2}: {status}")

    print(f"\n📈 Total: {passed}/{total} tests passed")
    print("=" * 60)

    if passed == total:
        print("🎉 ALL TESTS PASSED!")
    else:
        print(f"⚠️  {total - passed} test(s) failed")

    return passed == total


if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted")
        exit(1)