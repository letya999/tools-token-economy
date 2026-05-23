import time
from typing import Optional

class RateLimiter:
    """
    Simple Rate Limiter to respect RPM (Requests Per Minute) limits.
    Uses blocking sleep.
    """
    def __init__(self, requests_per_minute: int):
        self.delay = 60.0 / requests_per_minute
        self.last_call_time: Optional[float] = None

    def __enter__(self):
        if self.last_call_time is not None:
            elapsed = time.time() - self.last_call_time
            wait_time = self.delay - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.last_call_time = time.time()
