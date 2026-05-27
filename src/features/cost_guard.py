"""
CostGuard: safety mechanism to prevent budget overruns during benchmark.
"""
import logging
from typing import Any

_log = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when benchmark suite budget is exceeded."""
    pass


class CostGuard:
    def __init__(
        self,
        max_suite_usd: float = 5.0,
        max_config_usd: float = 0.50,
        max_tokens_per_config: int = 1_000_000
    ):
        self.max_suite_usd = max_suite_usd
        self.max_config_usd = max_config_usd
        self.max_tokens_per_config = max_tokens_per_config
        
        self.total_cost = 0.0
        self.total_tokens = 0
        self.config_stats: dict[str, dict[str, Any]] = {}

    def check_suite_budget(self, next_config_id: str):
        """Raise BudgetExceededError if suite budget is already exhausted."""
        if self.total_cost >= self.max_suite_usd:
            _log.error("Suite budget EXCEEDED ($%.2f >= $%.2f). Aborting.", self.total_cost, self.max_suite_usd)
            raise BudgetExceededError(f"Suite budget of ${self.max_suite_usd} exceeded")
        remaining = self.max_suite_usd - self.total_cost
        if remaining < self.max_config_usd * 0.5:
            _log.warning(
                "Suite budget nearly exhausted ($%.3f remaining < $%.3f per-config limit). "
                "Skipping config %s.",
                remaining, self.max_config_usd, next_config_id,
            )
            raise BudgetExceededError(
                f"Insufficient suite budget (${remaining:.3f}) to safely run config '{next_config_id}'"
            )

    def record(self, config_id: str, cost: float, tokens: int) -> dict[str, bool]:
        """Record usage and return exceed flags."""
        self.total_cost += cost
        self.total_tokens += tokens
        self.config_stats[config_id] = {"cost": cost, "tokens": tokens}

        flags = {
            "cost_exceeded": cost > self.max_config_usd,
            "token_exceeded": tokens > self.max_tokens_per_config
        }
        
        if flags["cost_exceeded"]:
            _log.warning("Config %s exceeded per-config budget ($%.2f > $%.2f)", config_id, cost, self.max_config_usd)
        if flags["token_exceeded"]:
            _log.warning("Config %s exceeded per-config token limit (%d > %d)", config_id, tokens, self.max_tokens_per_config)

        return flags

    @property
    def suite_summary(self) -> dict[str, Any]:
        return {
            "total_cost_usd": self.total_cost,
            "total_tokens": self.total_tokens,
            "config_count": len(self.config_stats),
            "remaining_budget_usd": max(0, self.max_suite_usd - self.total_cost)
        }
