"""
Cross-task statistical aggregation for external validity.

Implements the Friedman test and Nemenyi post-hoc critical difference for ranking
tool configs across multiple tasks. Reference:
  Demsar (2006), "Statistical Comparisons of Classifiers over Multiple Data Sets",
  Journal of Machine Learning Research 7, 1-30.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

# Q_alpha / sqrt(2) table for alpha=0.05. Source: Demsar (2006), Table 5.
Q_ALPHA_05: dict[int, float] = {
    2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728, 6: 2.850, 7: 2.949,
    8: 3.031, 9: 3.102, 10: 3.164, 11: 3.219, 12: 3.268, 13: 3.313,
    14: 3.354, 15: 3.391, 16: 3.424, 17: 3.456, 18: 3.485, 19: 3.513,
    20: 3.539,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _regularized_lower_gamma(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) via series expansion."""
    if x <= 0.0:
        return 0.0
    term = 1.0 / a
    total = term
    for n in range(1, 300):
        term *= x / (a + n)
        total += term
        if abs(term) < 1e-15 * abs(total):
            break
    try:
        return min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * total)
    except (ValueError, OverflowError):
        return 1.0


def _chi2_sf(x: float, df: int) -> float:
    """Chi-squared survival function P(X > x | df)."""
    try:
        from scipy.stats import chi2 as _sc_chi2  # type: ignore[import]
        return float(_sc_chi2.sf(x, df))
    except ImportError:
        if x <= 0.0:
            return 1.0
        p = _regularized_lower_gamma(df / 2.0, x / 2.0)
        return max(0.0, 1.0 - p)


def _spearman_rho(a: list[float], b: list[float]) -> float:
    """Spearman rank correlation via Pearson applied to the rank vectors."""
    if len(a) < 2:
        return float("nan")
    a_arr = np.array(a, dtype=float)
    b_arr = np.array(b, dtype=float)
    a_mean = float(a_arr.mean())
    b_mean = float(b_arr.mean())
    num = float(np.sum((a_arr - a_mean) * (b_arr - b_mean)))
    denom = float(
        np.sqrt(np.sum((a_arr - a_mean) ** 2) * np.sum((b_arr - b_mean) ** 2))
    )
    return num / denom if denom > 0.0 else float("nan")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_rank_matrix(
    per_task_results: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Build a config x task rank matrix.

    Args:
        per_task_results: {task_name -> {config_id -> median_net_spt}}.
            None / NaN entries mean the config has no valid result for that task.

    Returns:
        {config_id -> {task_name -> rank}} where rank 1 = best (highest net_spt).
        Configs with no valid score for a task get NaN rank for that task.
    """
    all_configs: set[str] = set()
    for scores in per_task_results.values():
        all_configs.update(scores.keys())

    rank_matrix: dict[str, dict[str, float]] = {c: {} for c in all_configs}

    for task_name, scores in per_task_results.items():
        valid = {
            c: s for c, s in scores.items()
            if s is not None and not math.isnan(s)
        }
        sorted_cfgs = sorted(valid, key=lambda c: valid[c], reverse=True)

        # Average rank for ties
        i = 0
        while i < len(sorted_cfgs):
            j = i
            while j < len(sorted_cfgs) and valid[sorted_cfgs[j]] == valid[sorted_cfgs[i]]:
                j += 1
            avg_rank = (i + 1 + j) / 2.0
            for c in sorted_cfgs[i:j]:
                rank_matrix[c][task_name] = avg_rank
            i = j

        for c in all_configs:
            if task_name not in rank_matrix[c]:
                rank_matrix[c][task_name] = float("nan")

    return rank_matrix


def average_ranks(
    rank_matrix: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Compute per-config average rank across tasks (NaN entries excluded).

    Returns:
        {config_id -> avg_rank}. Lower is better (rank 1 = best).
    """
    avg: dict[str, float] = {}
    for config_id, task_ranks in rank_matrix.items():
        valid = [r for r in task_ranks.values() if not math.isnan(r)]
        avg[config_id] = sum(valid) / len(valid) if valid else float("nan")
    return avg


def friedman_test(
    rank_matrix: dict[str, dict[str, float]],
) -> tuple[float, float, int, int]:
    """Friedman chi-squared test over the rank matrix.

    Formula (Demsar 2006, eq. 2):
        chi2_F = 12N / (k(k+1)) * (sum_j R_j^2 - k(k+1)^2/4)
    where R_j = AVERAGE rank of config j across N tasks (not sum).

    Only tasks where every config has a valid rank are included.

    Returns:
        (stat, p_value, k, n) where k = configs, n = tasks used.
    """
    all_tasks: set[str] = set()
    for task_ranks in rank_matrix.values():
        all_tasks.update(t for t, r in task_ranks.items() if not math.isnan(r))

    valid_tasks = [
        t for t in all_tasks
        if all(
            not math.isnan(rank_matrix[c].get(t, float("nan")))
            for c in rank_matrix
        )
    ]

    k = len(rank_matrix)
    n = len(valid_tasks)
    if k < 2 or n < 2:
        return 0.0, 1.0, k, n

    avg_r = {
        c: sum(rank_matrix[c][t] for t in valid_tasks) / n
        for c in rank_matrix
    }

    sum_sq = sum(r ** 2 for r in avg_r.values())
    stat = (12.0 * n) / (k * (k + 1)) * (sum_sq - k * (k + 1) ** 2 / 4.0)
    p_value = _chi2_sf(max(0.0, stat), df=k - 1)
    return stat, p_value, k, n


def nemenyi_cd(k: int, n: int, alpha: float = 0.05) -> float:
    """Nemenyi critical difference: CD = q_alpha * sqrt(k*(k+1) / (6*n)).

    Args:
        k: number of configs (must be in Q_ALPHA_05 table, 2-20).
        n: number of tasks.
        alpha: significance level (only 0.05 is tabulated; warning otherwise).

    Raises:
        ValueError: if k is outside the Q_ALPHA_05 table range.
    """
    if k not in Q_ALPHA_05:
        raise ValueError(
            f"k={k} outside Nemenyi Q_alpha table range 2-20; "
            "reduce the number of configs or extend the table."
        )
    return Q_ALPHA_05[k] * math.sqrt(k * (k + 1) / (6.0 * n))


def group_by_cd(
    avg_ranks: dict[str, float], cd: float
) -> list[list[str]]:
    """Group configs into overlapping CD groups.

    A config j is added to the current group if its rank is within CD of
    the group's first (best-ranked) member. Groups may overlap.

    Returns:
        List of groups ordered by group's minimum rank. Singletons (configs
        not within CD of any neighbour) are included as single-element groups.
    """
    sorted_cfgs = sorted(
        [(c, r) for c, r in avg_ranks.items() if not math.isnan(r)],
        key=lambda x: x[1],
    )
    if not sorted_cfgs:
        return []

    groups: list[list[str]] = []
    covered: set[str] = set()

    for i, (ci, ri) in enumerate(sorted_cfgs):
        group = [ci]
        for j in range(i + 1, len(sorted_cfgs)):
            cj, rj = sorted_cfgs[j]
            if rj - ri <= cd:
                group.append(cj)
            else:
                break
        if len(group) > 1:
            groups.append(group)
            covered.update(group)

    for c, _ in sorted_cfgs:
        if c not in covered:
            groups.append([c])

    groups.sort(key=lambda g: avg_ranks[g[0]])
    return groups


def cross_task_report(
    per_task_results: dict[str, dict[str, float]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Full cross-task statistical report.

    Args:
        per_task_results: {task_name -> {config_id -> median_net_spt}}.
        alpha: significance level for Friedman test and Nemenyi CD.

    Returns:
        dict with: rank_matrix, avg_ranks (sorted), friedman_stat, friedman_p,
        k, n, cd, cd_groups, consistent_winners, win_rate, is_significant.
    """
    rmat = build_rank_matrix(per_task_results)
    avg_r = average_ranks(rmat)
    stat, p_val, k, n = friedman_test(rmat)

    try:
        cd = nemenyi_cd(k, n, alpha=alpha)
    except ValueError:
        cd = float("nan")

    cd_groups = group_by_cd(avg_r, cd) if not math.isnan(cd) else []

    consistent_winners: list[str] = []
    if p_val < alpha and cd_groups and not math.isnan(cd):
        best_group = cd_groups[0]
        best_max = max(avg_r[c] for c in best_group if not math.isnan(avg_r[c]))
        second_min = min(
            (r for c, r in avg_r.items() if c not in best_group and not math.isnan(r)),
            default=float("inf"),
        )
        if second_min - best_max > cd:
            consistent_winners = list(best_group)

    tasks_list = list(per_task_results)
    win_rate: dict[str, float] = {
        c: (
            sum(1 for t in tasks_list if rmat[c].get(t, float("nan")) == 1.0)
            / len(tasks_list)
        )
        if tasks_list else 0.0
        for c in rmat
    }

    sorted_avg = dict(sorted(avg_r.items(), key=lambda x: x[1]))

    return {
        "rank_matrix": rmat,
        "avg_ranks": sorted_avg,
        "friedman_stat": stat,
        "friedman_p": p_val,
        "k": k,
        "n": n,
        "cd": cd,
        "cd_groups": cd_groups,
        "consistent_winners": consistent_winners,
        "win_rate": win_rate,
        "is_significant": p_val < alpha,
    }


def rank_stability(
    per_model_avg_ranks: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Cross-model rank stability via pairwise Spearman correlation.

    Args:
        per_model_avg_ranks: {model_name -> {config_id -> avg_rank}}
            as returned by average_ranks() for each model.

    Returns:
        dict with: correlations (pairwise), mean_correlation, stable_winners.
    """
    models = list(per_model_avg_ranks)
    if len(models) < 2:
        return {"correlations": {}, "mean_correlation": float("nan"), "stable_winners": []}

    common = set(per_model_avg_ranks[models[0]])
    for m in models[1:]:
        common &= set(per_model_avg_ranks[m])
    common_list = sorted(common)

    correlations: dict[str, float] = {}
    for i, m1 in enumerate(models):
        for m2 in models[i + 1:]:
            vec1 = [per_model_avg_ranks[m1][c] for c in common_list]
            vec2 = [per_model_avg_ranks[m2][c] for c in common_list]
            correlations[f"{m1}_vs_{m2}"] = _spearman_rho(vec1, vec2)

    mean_corr = (
        sum(correlations.values()) / len(correlations) if correlations else float("nan")
    )

    stable: list[str] = [
        c for c in common_list
        if all(
            per_model_avg_ranks[m][c] == min(per_model_avg_ranks[m].values())
            for m in models
        )
    ]

    return {
        "correlations": correlations,
        "mean_correlation": mean_corr,
        "stable_winners": stable,
    }
