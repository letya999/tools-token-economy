import time

from src.features.rate_limiter import RateLimiter


def test_rate_limiter_delay():
    # 10 RPM means 1 request every 6 seconds on average
    # For testing, we'll use a higher rate to save time, e.g., 60 RPM (1 per sec)
    limiter = RateLimiter(requests_per_minute=60)

    start_time = time.time()
    for _ in range(3):
        with limiter:
            pass
    end_time = time.time()

    # First call is immediate, second after 1s, third after 2s.
    # Total time should be at least 2 seconds.
    duration = end_time - start_time
    assert duration >= 2.0
