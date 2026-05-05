from streamload.utils.domain_resolver.circuit_breaker import CircuitBreaker


def test_starts_closed():
    cb = CircuitBreaker(threshold=3)
    assert cb.is_open("sc") is False


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(threshold=3)
    for _ in range(2):
        cb.record_failure("sc")
    assert cb.is_open("sc") is False
    cb.record_failure("sc")
    assert cb.is_open("sc") is True


def test_reset_clears_failures():
    cb = CircuitBreaker(threshold=2)
    cb.record_failure("sc")
    cb.record_failure("sc")
    assert cb.is_open("sc") is True
    cb.reset("sc")
    assert cb.is_open("sc") is False


def test_record_success_resets_failures():
    cb = CircuitBreaker(threshold=2)
    cb.record_failure("sc")
    cb.record_success("sc")
    cb.record_failure("sc")
    assert cb.is_open("sc") is False


def test_per_service_isolation():
    cb = CircuitBreaker(threshold=1)
    cb.record_failure("sc")
    assert cb.is_open("sc") is True
    assert cb.is_open("au") is False
