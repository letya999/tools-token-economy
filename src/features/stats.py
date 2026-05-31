"""Statistical utilities for benchmark run aggregation."""
from __future__ import annotations

import math
import random
from typing import Callable, Sequence


def coefficient_of_variation(values: Sequence[float]) -> float:
    """CV = std / mean. Returns inf if mean == 0, 0.0 if fewer than 2 values."""
    if len(values) < 2:
        return 0.0
    n = len(values)
    mean = sum(values) / n
    if mean == 0:
        return float("inf")
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance) / mean


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = median,
    n_resamples: int = 2000,
    alpha: float = 0.10,
    seed: int = 0,
) -> tuple[float, float]:
    """
    Bootstrap confidence interval at (1-alpha) level.
    Returns (lower, upper). Uses seed for reproducibility.
    """
    if len(values) < 2:
        v = values[0] if values else 0.0
        return (v, v)
    rng = random.Random(seed)
    estimates = []
    vals = list(values)
    n = len(vals)
    for _ in range(n_resamples):
        sample = [rng.choice(vals) for _ in range(n)]
        estimates.append(statistic(sample))
    estimates.sort()
    lo_idx = int(math.floor((alpha / 2) * n_resamples))
    hi_idx = int(math.ceil((1 - alpha / 2) * n_resamples)) - 1
    return (estimates[lo_idx], estimates[hi_idx])


def ci_overlap(ci_a: tuple[float, float], ci_b: tuple[float, float]) -> bool:
    """True if two CIs overlap (configs are statistically indistinguishable)."""
    return ci_a[0] <= ci_b[1] and ci_b[0] <= ci_a[1]


# Run validity statuses
STATUS_OK = "ok"
STATUS_LOW_CONFIDENCE = "low_confidence"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_UNSTABLE = "unstable"
CV_THRESHOLD = 0.5
MIN_VALID_RUNS_OK = 4
MIN_VALID_RUNS_LOW = 3


def run_validity_status(valid_values: Sequence[float]) -> str:
    """
    Determine ranking status for a config based on valid run values of a key metric
    (e.g. total_tokens or success_per_token).
    """
    n = len(valid_values)
    if n <= 2:
        return STATUS_INSUFFICIENT_DATA
    cv = coefficient_of_variation(valid_values)
    if cv > CV_THRESHOLD:
        return STATUS_UNSTABLE
    if n >= MIN_VALID_RUNS_OK:
        return STATUS_OK
    if n >= MIN_VALID_RUNS_LOW:
        return STATUS_LOW_CONFIDENCE
    return STATUS_INSUFFICIENT_DATA
