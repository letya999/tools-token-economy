"""Tests for cross_task.py Friedman/Nemenyi external validity module."""
import math

import pytest

from src.features.cross_task import (
    Q_ALPHA_05,
    average_ranks,
    build_rank_matrix,
    cross_task_report,
    friedman_test,
    group_by_cd,
    nemenyi_cd,
    rank_stability,
)


class TestBuildRankMatrix:
    def test_basic_ranking(self):
        per_task = {
            "t1": {"A": 100.0, "B": 50.0, "C": 25.0},
            "t2": {"A": 30.0, "B": 80.0, "C": 60.0},
        }
        m = build_rank_matrix(per_task)
        assert m["A"]["t1"] == 1.0
        assert m["B"]["t1"] == 2.0
        assert m["C"]["t1"] == 3.0
        assert m["B"]["t2"] == 1.0
        assert m["C"]["t2"] == 2.0
        assert m["A"]["t2"] == 3.0

    def test_tied_scores_average_rank(self):
        per_task = {"t1": {"A": 50.0, "B": 50.0, "C": 10.0}}
        m = build_rank_matrix(per_task)
        # A and B tied for rank 1-2 -> average rank 1.5
        assert m["A"]["t1"] == 1.5
        assert m["B"]["t1"] == 1.5
        assert m["C"]["t1"] == 3.0

    def test_missing_config_gets_nan(self):
        per_task = {
            "t1": {"A": 100.0, "B": 50.0},
            "t2": {"A": 80.0, "B": 60.0, "C": 40.0},
        }
        m = build_rank_matrix(per_task)
        assert math.isnan(m["C"]["t1"])
        assert not math.isnan(m["C"]["t2"])


class TestAverageRanks:
    def test_averages_correctly(self):
        rank_matrix = {
            "A": {"t1": 1.0, "t2": 3.0},
            "B": {"t1": 2.0, "t2": 1.0},
            "C": {"t1": 3.0, "t2": 2.0},
        }
        avg = average_ranks(rank_matrix)
        assert avg["A"] == pytest.approx(2.0)
        assert avg["B"] == pytest.approx(1.5)
        assert avg["C"] == pytest.approx(2.5)

    def test_nan_entries_excluded(self):
        rank_matrix = {"A": {"t1": 1.0, "t2": float("nan"), "t3": 3.0}}
        avg = average_ranks(rank_matrix)
        assert avg["A"] == pytest.approx(2.0)


class TestFriedmanTest:
    def test_one_config_always_wins(self):
        # A always rank 1, B always 2, C always 3 over 4 tasks.
        # chi2_F = 12*4/(3*4) * (1+4+9 - 3*16/4) = 4 * (14-12) = 8.0
        per_task = {
            f"t{i}": {"A": 100 - i, "B": 50 - i, "C": 10 - i}
            for i in range(4)
        }
        rmat = build_rank_matrix(per_task)
        stat, p, k, n = friedman_test(rmat)
        assert stat == pytest.approx(8.0, abs=1e-9)
        assert k == 3
        assert n == 4
        assert p < 0.05  # significant

    def test_all_tied_gives_zero_stat(self):
        per_task = {f"t{i}": {"A": 50.0, "B": 50.0, "C": 50.0} for i in range(4)}
        rmat = build_rank_matrix(per_task)
        stat, p, k, n = friedman_test(rmat)
        assert stat == pytest.approx(0.0, abs=1e-9)
        assert p > 0.99

    def test_insufficient_data_returns_trivial(self):
        # Only 1 task - can't compute meaningful stat
        rmat = build_rank_matrix({"t1": {"A": 100.0, "B": 50.0}})
        stat, p, k, n = friedman_test(rmat)
        assert stat == 0.0
        assert p == 1.0


class TestNemenyiCD:
    def test_k3_n5_formula(self):
        # CD = Q[3] * sqrt(3*4/(6*5)) = 2.343 * sqrt(0.4)
        expected = Q_ALPHA_05[3] * math.sqrt(3 * 4 / (6 * 5))
        assert nemenyi_cd(k=3, n=5) == pytest.approx(expected, rel=1e-6)

    def test_k2_n10(self):
        expected = Q_ALPHA_05[2] * math.sqrt(2 * 3 / (6 * 10))
        assert nemenyi_cd(k=2, n=10) == pytest.approx(expected, rel=1e-6)

    def test_invalid_k_raises(self):
        with pytest.raises(ValueError, match="outside Nemenyi Q_alpha table range"):
            nemenyi_cd(k=21, n=5)

    def test_k20_boundary(self):
        cd = nemenyi_cd(k=20, n=10)
        assert cd > 0.0


class TestGroupByCD:
    def test_overlapping_groups(self):
        avg_ranks = {"A": 1.0, "B": 1.5, "C": 3.0, "D": 3.4}
        groups = group_by_cd(avg_ranks, cd=1.0)
        group_sets = [set(g) for g in groups]
        assert {"A", "B"} in group_sets  # A and B within CD=1
        assert {"C", "D"} in group_sets  # C and D within CD=1
        # A and C are NOT in the same group (diff=2.0 > cd=1.0)
        assert not any("A" in g and "C" in g for g in groups)

    def test_singleton_included(self):
        avg_ranks = {"A": 1.0, "B": 5.0}
        groups = group_by_cd(avg_ranks, cd=0.5)
        all_configs = {c for g in groups for c in g}
        assert "A" in all_configs
        assert "B" in all_configs

    def test_empty_input(self):
        assert group_by_cd({}, cd=1.0) == []


class TestCrossTaskReport:
    def _dominant_data(self) -> dict:
        # A always wins across 12 tasks.
        # With k=3, n=12: CD = 2.343*sqrt(12/72) = 2.343*0.408 = 0.956 < 1.0 rank gap.
        # So A is clearly separated from B and C by > CD.
        return {
            f"t{i}": {"A": 100 - i, "B": 50 - i, "C": 10 - i}
            for i in range(12)
        }

    def test_significant_when_one_dominates(self):
        report = cross_task_report(self._dominant_data())
        assert report["is_significant"]
        assert "A" in report["consistent_winners"]
        assert report["friedman_p"] < 0.05

    def test_avg_ranks_sorted(self):
        report = cross_task_report(self._dominant_data())
        ranks = list(report["avg_ranks"].values())
        assert ranks == sorted(ranks)

    def test_win_rate_correct(self):
        report = cross_task_report(self._dominant_data())
        assert report["win_rate"]["A"] == pytest.approx(1.0)
        assert report["win_rate"]["B"] == pytest.approx(0.0)

    def test_not_significant_when_equal(self):
        per_task = {f"t{i}": {"A": 50.0, "B": 50.0, "C": 50.0} for i in range(6)}
        report = cross_task_report(per_task)
        assert not report["is_significant"]
        assert report["consistent_winners"] == []

    def test_keys_present(self):
        report = cross_task_report(self._dominant_data())
        for key in ("rank_matrix", "avg_ranks", "friedman_stat", "friedman_p",
                    "k", "n", "cd", "cd_groups", "consistent_winners", "win_rate",
                    "is_significant"):
            assert key in report


class TestRankStability:
    def test_perfect_correlation(self):
        per_model = {
            "gpt": {"A": 1.0, "B": 2.0, "C": 3.0},
            "claude": {"A": 1.0, "B": 2.0, "C": 3.0},
        }
        result = rank_stability(per_model)
        assert result["mean_correlation"] == pytest.approx(1.0, abs=1e-9)

    def test_inverse_correlation(self):
        per_model = {
            "gpt": {"A": 1.0, "B": 2.0, "C": 3.0},
            "claude": {"A": 3.0, "B": 2.0, "C": 1.0},
        }
        result = rank_stability(per_model)
        assert result["mean_correlation"] == pytest.approx(-1.0, abs=1e-9)

    def test_stable_winners(self):
        per_model = {
            "gpt": {"A": 1.0, "B": 2.5, "C": 3.0},
            "claude": {"A": 1.0, "B": 3.0, "C": 2.5},
        }
        result = rank_stability(per_model)
        assert "A" in result["stable_winners"]

    def test_single_model_returns_empty(self):
        result = rank_stability({"gpt": {"A": 1.0, "B": 2.0}})
        assert result["correlations"] == {}
        assert math.isnan(result["mean_correlation"])
