import glob
import json
import os
from datetime import datetime
from html import escape as h
from typing import Any

from src.features.significance import rank_with_tiebands, partition_by_status
from src.features.stats import STATUS_OK, STATUS_LOW_CONFIDENCE

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

# ── Fallback defaults (used when YAML config is missing) ────────────────────
_DEFAULT_EVAL_WEIGHTS: dict[str, float] = {
    "task_solved_score":       0.35,
    "correctness_score":       0.20,
    "context_quality_score":   0.15,
    "minimality_score":        0.10,
    "tool_correctness_score":  0.10,
    "pattern_adherence_score": 0.05,
    "tool_sequence_score":     0.05,
}

_DEFAULT_ALL_METRICS: dict[str, dict] = {
    "task_solved_score":       {"weight": 0.180, "direction": "higher", "description": "Agent fulfilled the user request"},
    "correctness_score":       {"weight": 0.120, "direction": "higher", "description": "Code is technically correct and bug-free"},
    "tool_correctness_score":  {"weight": 0.090, "direction": "higher", "description": "Tools used with correct args in correct context"},
    "context_quality_score":   {"weight": 0.090, "direction": "higher", "description": "Gathered context was relevant and sufficient"},
    "minimality_score":        {"weight": 0.060, "direction": "higher", "description": "No unnecessary changes or tool calls"},
    "pattern_adherence_score": {"weight": 0.030, "direction": "higher", "description": "Followed project conventions and style"},
    "tool_sequence_score":     {"weight": 0.030, "direction": "higher", "description": "Tool call sequence was logical and efficient"},
    "retrieval_precision":     {"weight": 0.050, "direction": "higher", "description": "Fraction of read files that were actually needed"},
    "retrieval_recall":        {"weight": 0.035, "direction": "higher", "description": "Fraction of needed files that were actually read"},
    "total_tokens":            {"weight": 0.035, "direction": "lower",  "description": "Total tokens consumed (input + output + tool)"},
    "cost_usd":                {"weight": 0.040, "direction": "lower",  "description": "API cost in USD"},
    "duration_sec":            {"weight": 0.010, "direction": "lower",  "description": "Wall-clock time to complete the task"},
    "model_calls":             {"weight": 0.020, "direction": "lower",  "description": "Number of LLM API calls made"},
    "errors":                  {"weight": 0.040, "direction": "lower",  "description": "Runtime errors encountered during execution"},
    "tool_errors":             {"weight": 0.040, "direction": "lower",  "description": "Tool call failures (wrong args, timeouts, etc.)"},
    "avg_tokens_per_tool":     {"weight": 0.040, "direction": "lower",  "description": "Token weight per tool response (lower is more efficient)"},
    "time_to_target":          {"weight": 0.030, "direction": "lower",  "description": "Number of cycles before first required file was read"},
    "context_waste_ratio":     {"weight": 0.060, "direction": "lower",  "description": "Fraction of read tokens that were NOT from required files"},
}

# Fields where 0 is the ideal "lower is better" value; use 1/(1+val) normalization
_ZERO_OK_LOWER = {"errors", "tool_errors", "time_to_target", "context_waste_ratio"}

_WEIGHTS_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "configs", "benchmark_weights.yaml"
)


def load_weights_config(config_path: str | None = None) -> tuple:
    """Return (eval_weights, all_metrics_weights) from YAML, falling back to defaults."""
    path = config_path or _WEIGHTS_CONFIG_PATH
    if not _HAS_YAML or not os.path.exists(path):
        return _DEFAULT_EVAL_WEIGHTS, _DEFAULT_ALL_METRICS
    try:
        with open(path, encoding="utf-8") as f:
            cfg = _yaml.safe_load(f)
        eval_w = cfg.get("eval_weights", _DEFAULT_EVAL_WEIGHTS)
        raw = cfg.get("all_metrics_weights", {})
        all_w = {
            field: {
                "weight": float(spec.get("weight", 0.0)),
                "direction": spec.get("direction", "higher"),
                "description": spec.get("description", ""),
            }
            for field, spec in raw.items()
            if isinstance(spec, dict)
        } or _DEFAULT_ALL_METRICS
        return eval_w, all_w
    except Exception:
        return _DEFAULT_EVAL_WEIGHTS, _DEFAULT_ALL_METRICS


def _normalize_configs(configs: list[dict], all_metrics_w: dict[str, dict]) -> list[dict[str, float]]:
    """Normalize each metric to [0, 1] for the all-metrics composite."""
    mins: dict[str, float] = {}
    for field, spec in all_metrics_w.items():
        if spec["direction"] == "lower" and field not in _ZERO_OK_LOWER:
            vals = [float(c.get(field, 0)) for c in configs if float(c.get(field, 0)) > 0]
            mins[field] = min(vals) if vals else 1.0

    result = []
    for c in configs:
        norm: dict[str, float] = {}
        for field, spec in all_metrics_w.items():
            val = float(c.get(field, 0.0))
            if spec["direction"] == "higher":
                norm[field] = max(0.0, min(1.0, val))
            elif field in _ZERO_OK_LOWER:
                norm[field] = 1.0 / (1.0 + val)
            else:
                min_val = mins.get(field, 1.0)
                norm[field] = min_val / max(val, min_val) if val > 0 else 0.0
        result.append(norm)
    return result


def compute_full_composite(norm_scores: dict[str, float], all_metrics_w: dict[str, dict]) -> float:
    """Weighted geometric mean of normalized all-metrics scores (weights sum to 1)."""
    _EPS = 0.001
    product = 1.0
    for field, spec in all_metrics_w.items():
        val = max(norm_scores.get(field, 0.0), _EPS)
        product *= val ** spec["weight"]
    return product


def generate_dashboard(
    results_dir: str,
    output_path: str,
    weights_config_path: str | None = None,
    aggregated_data: list[dict] | None = None,
) -> str:
    """
    Generate HTML dashboard and write to output_path.
    If aggregated_data is provided, it's a multi-run session.
    Otherwise, it loads the latest single-run data from results_dir.
    """
    eval_weights, all_metrics_w = load_weights_config(weights_config_path)

    is_multi_run = aggregated_data is not None
    if is_multi_run:
        configs = aggregated_data
    else:
        # Single-run legacy path
        from src.features.dashboard_builder import load_latest_per_config
        latest_data = load_latest_per_config(results_dir)
        configs = list(latest_data.values())

    # Ensure basics
    for cfg in configs:
        cfg.setdefault("total_tokens", cfg.get("input_tokens", 0) + cfg.get("output_tokens", 0) + cfg.get("tool_tokens", 0))
        cfg.setdefault("cost_usd", 0.0)
        # For aggregated data, 'net_spt' might already be the median
        if not is_multi_run:
            # Re-calculate net_spt for single run if missing
            from src.core.models import RunMetrics
            try:
                m = RunMetrics(**cfg)
                cfg["net_spt"] = m.net_spt
            except Exception:
                cfg.setdefault("net_spt", 0.0)

    # Normalize for full composite
    norm_list = _normalize_configs(configs, all_metrics_w)
    for cfg, norm in zip(configs, norm_list, strict=False):
        cfg["full_composite"] = compute_full_composite(norm, all_metrics_w)
        cfg["_norm"] = norm

    html = _render_html(configs, eval_weights, all_metrics_w, is_multi_run)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _render_html(
    configs: list[dict[str, Any]],
    eval_weights: dict[str, float],
    all_metrics_w: dict[str, dict],
    is_multi_run: bool = False
) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    model_name = configs[0].get("model_name", "Unknown") if configs else "N/A"
    eval_fields = list(eval_weights.keys())

    # Partition and Rank
    ranked, not_ranked = partition_by_status(configs)
    
    # We rank by net_spt (headline efficiency)
    metric_key = "net_spt" if not is_multi_run else "net_spt_median"
    ci_lo = "net_spt_ci_lo" if is_multi_run else metric_key
    ci_hi = "net_spt_ci_hi" if is_multi_run else metric_key
    
    winners = rank_with_tiebands(ranked, metric_key, ci_lo, ci_hi)
    
    # Helper to render rows
    def render_row(c: dict, rank: int | str = ""):
        ok = c.get("success", False) if not is_multi_run else (c.get("success_rate", 0) > 0.5)
        band = c.get("tie_band", "")
        note = c.get("rank_note", "")
        
        # Color class
        if not ok: cls = "fail-rank"
        elif rank and int(rank) <= 3: cls = "top-rank"
        else: cls = ""
            
        val_spt = c.get(metric_key, 0.0)
        ci_str = f"[{c.get(ci_lo, 0.0):.1f}, {c.get(ci_hi, 0.0):.1f}]" if is_multi_run else ""
        
        return f"""
        <tr class="{cls}" data-name="{h(c.get('config_name', '').lower(), quote=True)}">
            <td>{rank}</td>
            <td>{band}</td>
            <td><b>{h(c.get('config_name', ''))}</b><br><small style="color:var(--text-dim)">{note}</small></td>
            <td>{'✓' if ok else '✗'}</td>
            <td data-val="{val_spt:.2f}"><b>{val_spt:.1f}</b><br><small>{ci_str}</small></td>
            <td data-val="{c.get('eval_composite_median', c.get('eval_score', 0.0)):.3f}">{c.get('eval_composite_median', c.get('eval_score', 0.0)):.3f}</td>
            <td data-val="{c.get('total_tokens_median', c.get('total_tokens', 0))}">{int(c.get('total_tokens_median', c.get('total_tokens', 0))):,}</td>
            <td data-val="{c.get('cost_median', c.get('cost_usd', 0.0)):.4f}">${c.get('cost_median', c.get('cost_usd', 0.0)):.3f}</td>
            <td>{c.get('_validity_status', 'N/A')}</td>
            <td>{c.get('n_valid', 1)}/{c.get('n_total', 1)}</td>
        </tr>"""

    t1_rows = "".join(render_row(c, c['rank']) for c in winners)
    
    not_ranked_rows = ""
    for c in not_ranked:
        not_ranked_rows += f"""
        <tr class="fail-rank">
            <td>-</td>
            <td>-</td>
            <td>{h(c.get('config_name', ''))}</td>
            <td>{c.get('_validity_status', 'INVALID')}</td>
            <td colspan="6">Reason: {h(str(c.get('_validity_status', 'Unknown')))}. Suggested runs: +{c.get('_suggested_additional_runs', 0)}</td>
        </tr>"""

    banner = ""
    if not is_multi_run:
        banner = """<div class="warning-banner">
            ⚠️ <b>SINGLE RUN SESSION</b> — Results lack statistical significance. 
            Run with <code>--runs 5</code> or more to enable tie-bands and reliability checks.
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Benchmark — {timestamp}</title>
<style>
:root {{
    --bg:#0f1117; --surface:#1a1d27; --surface2:#212531;
    --text:#e0e0e0; --text-dim:#a0a0a0;
    --accent:#4f46e5; --success:#10b981; --warning:#f59e0b; --danger:#ef4444;
    --border:#2d313d;
}}
*{{box-sizing:border-box}}
body{{font-family:'Segoe UI',sans-serif;background:var(--bg);color:var(--text);margin:0;padding:20px}}
h1{{color:#fff;margin-bottom:4px}}
.meta{{color:var(--text-dim);margin-bottom:18px;font-size:13px;line-height:1.6}}
.warning-banner{{background:rgba(245,158,11,0.1);border:1px solid var(--warning);color:var(--warning);padding:12px;border-radius:8px;margin-bottom:20px;font-size:14px}}
table{{width:100%;border-collapse:collapse;background:var(--surface);border-radius:8px;overflow:hidden;margin-bottom:24px;border:1px solid var(--border);font-size:13px}}
th,td{{padding:12px 14px;text-align:left;border-bottom:1px solid var(--border)}}
th{{background:#252936;color:#fff;cursor:pointer;user-select:none}}
tr:nth-child(even){{background:var(--surface2)}}
tr:hover{{background:#2d3242}}
.top-rank{{border-left:4px solid var(--success)}}
.fail-rank{{opacity:.6;filter:grayscale(0.5)}}
.composite-cell{{font-weight:bold;color:var(--accent)}}
</style>
</head>
<body>
<h1>Benchmark Results</h1>
<div class="meta">
    Generated: {timestamp} | Model: {h(model_name)} | Metric: net_spt (Efficiency)
</div>

{banner}

<h2>Ranked Results (Significance-Aware)</h2>
<table>
    <thead><tr>
        <th>Rank</th>
        <th>Band</th>
        <th>Config</th>
        <th>Success</th>
        <th>Net SPT (Median + 90% CI)</th>
        <th>Eval Score</th>
        <th>Tokens</th>
        <th>Cost</th>
        <th>Status</th>
        <th>Runs</th>
    </tr></thead>
    <tbody>{t1_rows}</tbody>
</table>

{f'<h2>Not Ranked (Unstable / Insufficient Data)</h2><table><thead><tr><th>#</th><th>Band</th><th>Config</th><th>Status</th><th colspan="6">Details</th></tr></thead><tbody>{not_ranked_rows}</tbody></table>' if not_ranked_rows else ''}

</body>
</html>"""


def load_latest_per_config(results_dir: str) -> dict[str, dict[str, Any]]:
    """For each config ID return the metrics dict from the most recent run."""
    runs = glob.glob(os.path.join(results_dir, "run_*", "metrics.json"))
    latest: dict[str, tuple] = {}
    for r in runs:
        folder_name = os.path.basename(os.path.dirname(r))
        parts = folder_name.split("_")
        if len(parts) >= 4:
            ts = f"{parts[1]}_{parts[2]}"
            
            # Identify repetition if present
            rep_idx = -1
            for i, p in enumerate(parts):
                if p.startswith("r") and len(p) == 4 and p[1:].isdigit():
                    rep_idx = i
                    break
            
            if rep_idx != -1:
                cid = parts[rep_idx+1]
                cname = "_".join(parts[rep_idx+1:])
            else:
                cid = parts[3]
                cname = "_".join(parts[3:])

            try:
                with open(r, encoding="utf-8") as f:
                    m = json.load(f)
                m.setdefault("config_id", cid)
                m.setdefault("config_name", cname)
                if cid not in latest or ts > latest[cid][0]:
                    latest[cid] = (ts, m)
            except (OSError, json.JSONDecodeError):
                continue
    return {cid: data[1] for cid, data in sorted(latest.items())}


def find_last_full_run_timestamp(results_dir: str) -> str | None:
    """Find the timestamp of the latest full benchmark run in the results directory."""
    runs = glob.glob(os.path.join(results_dir, "run_*"))
    timestamps = []
    import re
    ts_pattern = re.compile(r"run_(\d{8}_\d{6})_")
    for r in runs:
        m = ts_pattern.search(os.path.basename(r))
        if m:
            timestamps.append(m.group(1))
    return max(timestamps) if timestamps else None
