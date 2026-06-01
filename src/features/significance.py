from typing import Any
from src.features.stats import ci_overlap

def rank_with_tiebands(configs: list[dict[str, Any]], metric_key: str, ci_key_lo: str, ci_key_hi: str) -> list[dict[str, Any]]:
    """
    Sorts configs by point estimate descending, then assigns a tie_band integer.
    Configs whose CIs overlap with the current band leader share the band.
    
    Args:
        configs: List of aggregated config dictionaries.
        metric_key: The key for the point estimate (e.g., 'net_spt_median').
        ci_key_lo: The key for the lower bound of the CI.
        ci_key_hi: The key for the upper bound of the CI.
        
    Returns:
        The list of configs annotated with 'rank', 'tie_band', and 'rank_note'.
    """
    if not configs:
        return []
        
    # Sort by point estimate descending
    sorted_configs = sorted(configs, key=lambda x: x.get(metric_key, 0.0), reverse=True)
    
    ranked_configs = []
    current_band = 1
    band_leader = sorted_configs[0]
    
    # Store band start/end for the rank_note
    band_start_idx = 0
    
    for i, cfg in enumerate(sorted_configs):
        # Check if CI overlaps with the band leader
        leader_ci = (band_leader.get(ci_key_lo, 0.0), band_leader.get(ci_key_hi, 0.0))
        current_ci = (cfg.get(ci_key_lo, 0.0), cfg.get(ci_key_hi, 0.0))
        
        if not ci_overlap(leader_ci, current_ci):
            # No overlap -> new band
            current_band += 1
            band_leader = cfg
            band_start_idx = i
            
        cfg_out = cfg.copy()
        cfg_out['rank'] = i + 1
        cfg_out['tie_band'] = current_band
        ranked_configs.append(cfg_out)
        
    # Second pass to add rank_note "tied with #X-#Y"
    # Group by tie_band
    bands = {}
    for cfg in ranked_configs:
        b = cfg['tie_band']
        if b not in bands:
            bands[b] = []
        bands[b].append(cfg)
        
    for cfg in ranked_configs:
        band_members = bands[cfg['tie_band']]
        if len(band_members) > 1:
            first = band_members[0]['rank']
            last = band_members[-1]['rank']
            if first != last:
                cfg['rank_note'] = f"tied with #{first}-#{last}"
            else:
                cfg['rank_note'] = ""
        else:
            cfg['rank_note'] = ""
            
    return ranked_configs

def partition_by_status(configs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Partitions configs into 'ranked' and 'not_ranked' based on validity status.
    
    Args:
        configs: List of aggregated config dictionaries.
        
    Returns:
        A tuple (ranked, not_ranked).
    """
    from src.features.stats import STATUS_OK, STATUS_LOW_CONFIDENCE
    
    ranked = []
    not_ranked = []
    
    for cfg in configs:
        status = cfg.get('_validity_status', '')
        if status in (STATUS_OK, STATUS_LOW_CONFIDENCE):
            ranked.append(cfg)
        else:
            not_ranked.append(cfg)
            
    return ranked, not_ranked
