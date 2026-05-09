from streamload.streaming.ram_buffer import RamRingBuffer


def test_set_get_within_capacity():
    rb = RamRingBuffer(capacity=3)
    rb.set("a", b"1")
    rb.set("b", b"2")
    assert rb.get("a") == b"1"
    assert rb.get("b") == b"2"


def test_evicts_oldest_when_full():
    rb = RamRingBuffer(capacity=2)
    rb.set("a", b"1"); rb.set("b", b"2"); rb.set("c", b"3")
    assert rb.get("a") is None
    assert rb.get("b") == b"2"
    assert rb.get("c") == b"3"


def test_get_nonexistent_returns_none():
    rb = RamRingBuffer(capacity=2)
    assert rb.get("x") is None


def test_get_promotes_to_recent():
    rb = RamRingBuffer(capacity=2)
    rb.set("a", b"1"); rb.set("b", b"2")
    rb.get("a")  # touches a
    rb.set("c", b"3")  # should evict b, not a
    assert rb.get("a") == b"1"
    assert rb.get("b") is None
