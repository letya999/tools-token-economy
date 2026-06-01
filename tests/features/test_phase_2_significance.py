import pytest
from src.features.significance import rank_with_tiebands, partition_by_status
from src.features.stats import STATUS_OK, STATUS_LOW_CONFIDENCE, STATUS_UNSTABLE, STATUS_INSUFFICIENT_DATA

def test_rank_with_tiebands():
    # Scenario: 3 configs, A and B overlap, C is disjoint (worse)
    configs = [
        {"config_id": "A", "net_spt_median": 10.0, "net_spt_ci_lo": 8.0, "net_spt_ci_hi": 12.0},
        {"config_id": "B", "net_spt_median": 9.0, "net_spt_ci_lo": 7.0, "net_spt_ci_hi": 11.0},
        {"config_id": "C", "net_spt_median": 5.0, "net_spt_ci_lo": 4.0, "net_spt_ci_hi": 6.0},
    ]
    
    ranked = rank_with_tiebands(configs, "net_spt_median", "net_spt_ci_lo", "net_spt_ci_hi")
    
    assert len(ranked) == 3
    assert ranked[0]["config_id"] == "A"
    assert ranked[1]["config_id"] == "B"
    assert ranked[2]["config_id"] == "C"
    
    # A and B overlap with A (leader), so they should share tie_band 1
    assert ranked[0]["tie_band"] == 1
    assert ranked[1]["tie_band"] == 1
    # C does not overlap with A, so it starts band 2
    assert ranked[2]["tie_band"] == 2
    
    # Check rank_note
    assert "tied with #1-#2" in ranked[0]["rank_note"]
    assert "tied with #1-#2" in ranked[1]["rank_note"]
    assert ranked[2]["rank_note"] == ""

def test_partition_by_status():
    configs = [
        {"config_id": "OK", "_validity_status": STATUS_OK},
        {"config_id": "LOW", "_validity_status": STATUS_LOW_CONFIDENCE},
        {"config_id": "UNSTABLE", "_validity_status": STATUS_UNSTABLE},
        {"config_id": "INSUFF", "_validity_status": STATUS_INSUFFICIENT_DATA},
    ]
    
    ranked, not_ranked = partition_by_status(configs)
    
    assert len(ranked) == 2
    assert ranked[0]["config_id"] == "OK"
    assert ranked[1]["config_id"] == "LOW"
    
    assert len(not_ranked) == 2
    assert not_ranked[0]["config_id"] == "UNSTABLE"
    assert not_ranked[1]["config_id"] == "INSUFF"
