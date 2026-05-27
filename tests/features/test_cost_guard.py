import pytest

from src.features.cost_guard import BudgetExceededError, CostGuard


@pytest.fixture
def guard():
    return CostGuard(max_suite_usd=1.0, max_config_usd=0.10, max_tokens_per_config=100_000)


def test_record_accumulates_totals(guard):
    guard.record("cfg_a", cost=0.05, tokens=10_000)
    guard.record("cfg_b", cost=0.04, tokens=8_000)
    assert guard.total_cost == pytest.approx(0.09)
    assert guard.total_tokens == 18_000


def test_record_returns_no_flags_within_limits(guard):
    flags = guard.record("cfg_a", cost=0.05, tokens=50_000)
    assert flags["cost_exceeded"] is False
    assert flags["token_exceeded"] is False


def test_record_flags_cost_exceeded(guard):
    flags = guard.record("cfg_a", cost=0.15, tokens=10_000)
    assert flags["cost_exceeded"] is True


def test_record_flags_token_exceeded(guard):
    flags = guard.record("cfg_a", cost=0.01, tokens=200_000)
    assert flags["token_exceeded"] is True


def test_check_suite_budget_passes_when_under_limit(guard):
    guard.record("cfg_a", cost=0.50, tokens=50_000)
    guard.check_suite_budget("cfg_b")  # should not raise


def test_check_suite_budget_raises_when_exceeded(guard):
    guard.record("cfg_a", cost=1.0, tokens=50_000)
    with pytest.raises(BudgetExceededError):
        guard.check_suite_budget("cfg_b")


def test_check_suite_budget_raises_when_nearly_exhausted(guard):
    # Remaining = $1.0 - $0.96 = $0.04, threshold = $0.10 * 0.5 = $0.05 → should raise
    guard.record("cfg_a", cost=0.96, tokens=10_000)
    with pytest.raises(BudgetExceededError):
        guard.check_suite_budget("cfg_b")


def test_check_suite_budget_passes_when_enough_remains(guard):
    # Remaining = $1.0 - $0.90 = $0.10, threshold = $0.05 → $0.10 >= $0.05 → no raise
    guard.record("cfg_a", cost=0.90, tokens=10_000)
    guard.check_suite_budget("cfg_b")  # should not raise


def test_suite_summary_structure(guard):
    guard.record("cfg_a", cost=0.30, tokens=30_000)
    summary = guard.suite_summary
    assert summary["total_cost_usd"] == pytest.approx(0.30)
    assert summary["total_tokens"] == 30_000
    assert summary["config_count"] == 1
    assert summary["remaining_budget_usd"] == pytest.approx(0.70)


def test_remaining_budget_floored_at_zero(guard):
    guard.record("cfg_a", cost=2.0, tokens=10_000)
    assert guard.suite_summary["remaining_budget_usd"] == 0.0
