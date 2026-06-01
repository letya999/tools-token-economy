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
        max_tokens_per_config: int = 1_000_000,
        max_judge_usd_per_run: float = 1.00
    ):
        self.max_suite_usd = max_suite_usd
        self.max_config_usd = max_config_usd
        self.max_tokens_per_config = max_tokens_per_config
        self.max_judge_usd_per_run = max_judge_usd_per_run
        
        self.total_cost = 0.0
        self.total_tokens = 0
        self.suite_judge_cost = 0.0
        self.session_cost = 0.0
        self.config_stats: dict[str, dict[str, Any]] = {}

    @property
    def session_total_cost(self) -> float:
        """Total cost accumulated across all suites in the session."""
        return self.session_cost + self.total_cost + self.suite_judge_cost

    def reset_suite(self):
        """Reset suite-level counters and accumulate to session cost."""
        self.session_cost += self.total_cost + self.suite_judge_cost
        self.total_cost = 0.0
        self.total_tokens = 0
        self.suite_judge_cost = 0.0
        self.config_stats = {}

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
        if config_id not in self.config_stats:
            self.config_stats[config_id] = {"cost": 0.0, "tokens": 0, "judge_cost": 0.0}
        
        self.config_stats[config_id]["cost"] += cost
        self.config_stats[config_id]["tokens"] += tokens

        flags = {
            "cost_exceeded": cost > self.max_config_usd,
            "token_exceeded": tokens > self.max_tokens_per_config
        }
        
        if flags["cost_exceeded"]:
            _log.warning("Config %s exceeded per-config budget ($%.2f > $%.2f)", config_id, cost, self.max_config_usd)
        if flags["token_exceeded"]:
            _log.warning("Config %s exceeded per-config token limit (%d > %d)", config_id, tokens, self.max_tokens_per_config)

        return flags

    def record_judge(self, config_id: str, judge_cost: float, judge_tokens: int):
        """Record judge usage for a run."""
        self.suite_judge_cost += judge_cost
        if config_id not in self.config_stats:
            self.config_stats[config_id] = {"cost": 0.0, "tokens": 0, "judge_cost": 0.0}
        self.config_stats[config_id]["judge_cost"] += judge_cost

    @property
    def suite_summary(self) -> dict[str, Any]:
        return {
            "total_cost_usd": self.total_cost,
            "total_tokens": self.total_tokens,
            "suite_judge_cost_usd": self.suite_judge_cost,
            "config_count": len(self.config_stats),
            "remaining_budget_usd": max(0, self.max_suite_usd - self.total_cost)
        }
