import glob
import json
import os
from datetime import datetime
from html import escape as h
from typing import Any

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
    "total_tokens":            {"weight": 0.045, "direction": "lower",  "description": "Total tokens consumed (input + output + tool)"},
    "cost_usd":                {"weight": 0.040, "direction": "lower",  "description": "API cost in USD"},
    "duration_sec":            {"weight": 0.020, "direction": "lower",  "description": "Wall-clock time to complete the task"},
    "model_calls":             {"weight": 0.020, "direction": "lower",  "description": "Number of LLM API calls made"},
    "errors":                  {"weight": 0.040, "direction": "lower",  "description": "Runtime errors encountered during execution"},
    "tool_errors":             {"weight": 0.040, "direction": "lower",  "description": "Tool call failures (wrong args, timeouts, etc.)"},
    "avg_tokens_per_tool":     {"weight": 0.040, "direction": "lower",  "description": "Token weight per tool response (lower is more efficient)"},
    "time_to_target":          {"weight": 0.030, "direction": "lower",  "description": "Number of cycles before first required file was read"},
    "context_waste_ratio":     {"weight": 0.040, "direction": "lower",  "description": "Fraction of read tokens that were NOT from required files"},
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


def compute_composite(scores: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted geometric mean of eval score fields (weights must sum to 1).
    Returns 0.0 if any contributing score is 0."""
    if not weights:
        return 0.0
    product = 1.0
    for key, w in weights.items():
        val = scores.get(key, 0.0)
        if val <= 0.0:
            return 0.0
        product *= val ** w
    return product


def _normalize_configs(configs: list[dict], all_metrics_w: dict[str, dict]) -> list[dict[str, float]]:
    """Normalize each metric to [0, 1] for the all-metrics composite.

    higher-is-better: value clipped to [0, 1] (eval scores already are).
    lower-is-better:  min/val ratio so the best (min) config scores 1.0.
    zero-ok-lower:    1/(1+val) so that val=0 gives 1.0 without division by zero.
    """
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
    """Weighted geometric mean of normalized all-metrics scores (weights sum to 1).
    Uses epsilon floor 0.001 so a single missing/zero field doesn't collapse the score
    — unlike eval composite, these 15 fields can legitimately be 0 for some agent
    architectures (e.g. agents that don't log file reads get retrieval_precision=0)."""
    _EPS = 0.001
    product = 1.0
    for field, spec in all_metrics_w.items():
        val = max(norm_scores.get(field, 0.0), _EPS)
        product *= val ** spec["weight"]
    return product


def find_last_full_run_timestamp(results_dir: str, total_configs: int) -> str | None:
    """Return most recent timestamp string where all N config IDs are present."""
    runs = glob.glob(os.path.join(results_dir, "run_*", "metrics.json"))
    ts_groups: dict[str, set] = {}
    for r in runs:
        parts = os.path.basename(os.path.dirname(r)).split("_")
        if len(parts) >= 4:
            ts = f"{parts[1]}_{parts[2]}"
            # Skip repetition infix if present
            cfg_idx = 3
            if parts[3].startswith("r") and len(parts[3]) == 4 and parts[3][1:].isdigit():
                cfg_idx = 4
            ts_groups.setdefault(ts, set()).add(parts[cfg_idx])
    for ts in sorted(ts_groups.keys(), reverse=True):
        if len(ts_groups[ts]) >= total_configs:
            return ts
    return None


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


def generate_dashboard(
    results_dir: str,
    output_path: str,
    weights_config_path: str | None = None,
) -> str:
    """Generate HTML dashboard and write to output_path. Returns output_path."""
    eval_weights, all_metrics_w = load_weights_config(weights_config_path)

    latest_data = load_latest_per_config(results_dir)
    configs = list(latest_data.values())

    for cfg in configs:
        cfg["total_tokens"] = cfg.get("total_tokens") or (
            cfg.get("input_tokens", 0) + cfg.get("output_tokens", 0) + cfg.get("tool_tokens", 0)
        )
        cfg.setdefault("cost_usd",
            (cfg.get("input_tokens", 0) * 0.1 + cfg.get("output_tokens", 0) * 0.4) / 1_000_000
        )
        cfg.setdefault("success_per_token",
            1_000_000.0 / cfg["total_tokens"] if cfg.get("success") and cfg["total_tokens"] > 0 else 0.0
        )
        cfg["composite_score"] = compute_composite(cfg, eval_weights)

    norm_list = _normalize_configs(configs, all_metrics_w)
    for cfg, norm in zip(configs, norm_list, strict=False):
        cfg["full_composite"] = compute_full_composite(norm, all_metrics_w)
        cfg["_norm"] = norm

    html = _render_html(configs, eval_weights, all_metrics_w)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _render_html(
    configs: list[dict[str, Any]],
    eval_weights: dict[str, float],
    all_metrics_w: dict[str, dict],
) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    model_name = configs[0].get("model_name", "Unknown") if configs else "N/A"
    eval_fields = list(eval_weights.keys())
    n = len(configs)

    # ── Table 1: Winners ────────────────────────────────────────────────────
    winners = sorted(configs, key=lambda x: x.get("composite_score", 0), reverse=True)
    t1_rows = ""
    for i, c in enumerate(winners):
        rank = i + 1
        ok = c.get("success", False)
        cls = "fail-rank" if not ok else ("top-rank" if rank <= 5 else ("mid-rank" if rank <= 10 else "low-rank"))
        comp = c.get("composite_score", 0.0)
        full = c.get("full_composite", 0.0)
        t1_rows += f"""
        <tr class="{cls}" data-name="{h(c['config_name'].lower(), quote=True)}" data-success="{str(ok).lower()}">
            <td>{rank}</td>
            <td>{h(c['config_name'])}</td>
            <td>{'✓' if ok else '✗'}</td>
            <td class="composite-cell" data-val="{comp:.6f}">
                <div class="bar-container"><div class="bar" style="width:{int(comp*100)}%"></div></div><span>{comp:.3f}</span>
            </td>
            <td class="composite-cell" data-val="{full:.6f}">
                <div class="bar-container"><div class="bar" style="width:{int(full*100)}%"></div></div><span>{full:.3f}</span>
            </td>
            <td data-val="{c['total_tokens']}">{c['total_tokens']:,}</td>
            <td data-val="{c['cost_usd']:.6f}">${c['cost_usd']:.4f}</td>
            <td data-val="{c['success_per_token']:.2f}">{c['success_per_token']:.1f}</td>
            <td data-val="{c.get('avg_tokens_per_tool', 0.0):.1f}">{c.get('avg_tokens_per_tool', 0.0):.1f}</td>
            <td data-val="{c.get('time_to_target', 0)}">{c.get('time_to_target', 0)}</td>
            <td data-val="{c.get('context_waste_ratio', 0.0):.2f}">{int(c.get('context_waste_ratio', 0.0)*100)}%</td>
            <td data-val="{c['duration_sec']:.1f}">{c['duration_sec']:.1f}s</td>
            <td data-val="{c.get('agent_cycles', 0)}">{c.get('agent_cycles', 0)}</td>
            <td data-val="{c.get('avg_tokens_per_tool', 0):.1f}">{c.get('avg_tokens_per_tool', 0):.0f}</td>
            <td data-val="{c.get('context_waste_ratio', 0):.3f}">{c.get('context_waste_ratio', 0):.1%}</td>
        </tr>"""

    # ── Table 2: Full details ────────────────────────────────────────────────
    # Short header labels for eval fields (derive from field name)
    _label = {
        "task_solved_score": "Solved", "tool_correctness_score": "Tools",
        "context_quality_score": "Ctx", "correctness_score": "Corr",
        "minimality_score": "Min", "pattern_adherence_score": "Patt",
        "tool_sequence_score": "Seq",
    }
    eval_headers = "".join(
        f'<th onclick="sortTable(\'table-details\',{12+i})" title="{h(f)}">{h(_label.get(f, f))}</th>'
        for i, f in enumerate(eval_fields)
    )
    comp_col_idx = 12 + len(eval_fields)

    t2_rows = ""
    for c in configs:
        ok = c.get("success", False)
        pass_text = "PASS" if ok else "FAIL"
        comp = c.get("composite_score", 0.0)
        full = c.get("full_composite", 0.0)
        judge_cols = "".join(
            f'<td class="score-cell" data-val="{c.get(f, 0.0):.3f}">'
            f'<div class="mini-bar" style="width:{int(c.get(f, 0.0)*100)}%"></div>'
            f'{c.get(f, 0.0):.2f}</td>'
            for f in eval_fields
        )
        t2_rows += f"""
        <tr data-name="{h(c['config_name'].lower(), quote=True)}" data-success="{str(ok).lower()}">
            <td>{h(str(c['config_id']))}</td>
            <td>{h(c['config_name'])}</td>
            <td class="status-{pass_text.lower()}">{pass_text}</td>
            <td>{h(str(c.get('execution_result', '')))}</td>
            <td data-val="{c['total_tokens']}">{c.get('input_tokens',0)}/{c.get('output_tokens',0)}/{c.get('tool_tokens',0)}/<b>{c['total_tokens']}</b></td>
            <td data-val="{c['cost_usd']:.6f}">${c['cost_usd']:.4f}</td>
            <td data-val="{c['duration_sec']:.1f}">{c['duration_sec']:.1f}s</td>
            <td>{c.get('model_calls', 0)}</td>
            <td>{c.get('tool_calls', 0)}</td>
            <td>{c.get('agent_cycles', 0)}</td>
            <td title="TTT: {c.get('time_to_target', 0)}, Waste: {c.get('context_waste_ratio', 0.0):.2f}">{c.get('time_to_target', 0)} / {int(c.get('context_waste_ratio', 0.0)*100)}%</td>
            <td>{c.get('retrieval_precision', 0):.2f}/{c.get('retrieval_recall', 0):.2f}</td>
            {judge_cols}
            <td class="composite-cell" data-val="{comp:.6f}"><b>{comp:.3f}</b></td>
            <td class="composite-cell" data-val="{full:.6f}"><b>{full:.3f}</b></td>
            <td>{c.get('files_read',0)}/{c.get('files_changed',0)}/{c.get('patch_lines',0)}</td>
            <td>{c.get('errors',0)}/{c.get('tool_errors',0)}</td>
            <td>{c.get('agent_cycles', 0)}</td>
            <td>{c.get('avg_tokens_per_tool', 0):.0f}</td>
            <td>{c.get('time_to_target', 0)}</td>
            <td>{c.get('context_waste_ratio', 0):.1%}</td>
            <td>{c.get('warmup_sec', 0):.1f}s</td>
            <td>{'Y' if c.get('made_changes') else 'N'}</td>
        </tr>"""

    # ── Table 3: Eval weights reference (collapsible) ───────────────────────
    _desc3 = {
        "task_solved_score":       "Did the agent accomplish the user's goal?",
        "correctness_score":       "Is the produced code correct and free of side effects?",
        "context_quality_score":   "Was gathered context relevant — did the agent over-read?",
        "minimality_score":        "Surgical edits only; no unnecessary file rewrites",
        "tool_correctness_score":  "Chose the right retrieval tool for the task",
        "pattern_adherence_score": "Follows existing project conventions and style",
        "tool_sequence_score":     "Logical ordering of tool call operations",
    }
    t3_rows = ""
    for field, weight in eval_weights.items():
        avg = sum(c.get(field, 0.0) for c in configs) / n if n else 0.0
        t3_rows += f"""
        <tr>
            <td><code>{h(field)}</code></td>
            <td>
                <div class="bar-container" style="width:120px"><div class="bar" style="width:{int(weight*100)}%"></div></div>
                <b>{weight:.3f}</b>
            </td>
            <td>
                <div class="bar-container" style="width:80px"><div class="bar avg-bar" style="width:{int(avg*100)}%"></div></div>
                {avg:.3f}
            </td>
            <td style="color:var(--text-dim);font-size:12px">{h(_desc3.get(field, ''))}</td>
        </tr>"""

    # ── Table 4: All-metrics weights (collapsible) ───────────────────────────
    t4_rows = ""
    for field, spec in all_metrics_w.items():
        w = spec["weight"]
        direction = spec["direction"]
        desc = spec["description"]
        avg_raw = sum(float(c.get(field, 0.0)) for c in configs) / n if n else 0.0
        avg_norm = sum(c.get("_norm", {}).get(field, 0.0) for c in configs) / n if n else 0.0
        dir_badge = '<span class="dir-higher">▲ higher</span>' if direction == "higher" else '<span class="dir-lower">▼ lower</span>'
        norm_bar_w = int(avg_norm * 100)
        t4_rows += f"""
        <tr>
            <td><code>{h(field)}</code></td>
            <td>{dir_badge}</td>
            <td>
                <div class="bar-container" style="width:120px"><div class="bar" style="width:{int(w*100)}%"></div></div>
                <b>{w:.3f}</b>
            </td>
            <td style="font-variant-numeric:tabular-nums">{avg_raw:.3f}</td>
            <td>
                <div class="bar-container" style="width:80px"><div class="bar avg-bar" style="width:{norm_bar_w}%"></div></div>
                {avg_norm:.3f}
            </td>
            <td style="color:var(--text-dim);font-size:12px">{h(desc)}</td>
        </tr>"""

    eval_w_info = " · ".join(f"{k.replace('_score', '')}: {v:.2f}" for k, v in eval_weights.items())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Benchmark Dashboard — {timestamp}</title>
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
.meta{{color:var(--text-dim);margin-bottom:18px;font-size:13px;line-height:1.9}}
.controls{{display:flex;gap:16px;align-items:center;background:var(--surface);padding:12px 16px;border-radius:8px;margin-bottom:20px;border:1px solid var(--border)}}
input[type=text]{{background:var(--bg);border:1px solid var(--border);color:#fff;padding:7px 12px;border-radius:4px;width:280px;font-size:13px}}
.btn-group{{display:flex;gap:4px}}
button{{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:7px 14px;cursor:pointer;border-radius:4px;font-size:13px}}
button.active{{background:var(--accent);border-color:var(--accent);color:#fff}}
table{{width:100%;border-collapse:collapse;background:var(--surface);border-radius:8px;overflow:hidden;margin-bottom:8px;border:1px solid var(--border);font-size:13px}}
th,td{{padding:9px 11px;text-align:left;border-bottom:1px solid var(--border)}}
th{{background:#252936;color:#fff;position:sticky;top:0;cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{background:#2d3242}}
tr:nth-child(even){{background:var(--surface2)}}
tr:hover{{background:#2d3242}}
.bar-container{{height:10px;background:#2a2d3a;border-radius:5px;display:inline-block;vertical-align:middle;margin-right:6px;overflow:hidden;width:100px}}
.bar{{height:100%;background:var(--accent)}}
.avg-bar{{background:var(--warning)}}
.composite-cell .bar{{background:linear-gradient(90deg,var(--danger) 0%,var(--warning) 50%,var(--success) 100%)}}
.mini-bar{{height:3px;background:var(--accent);margin-bottom:2px;border-radius:2px}}
.score-cell{{min-width:52px}}
.top-rank{{border-left:3px solid var(--success)}}
.mid-rank{{border-left:3px solid var(--warning)}}
.low-rank{{border-left:3px solid var(--danger)}}
.fail-rank{{opacity:.65;filter:grayscale(.4);border-left:3px solid #555}}
.status-pass{{color:var(--success);font-weight:600}}
.status-fail{{color:var(--danger);font-weight:600}}
code{{background:#252936;padding:1px 5px;border-radius:3px;font-size:12px}}
.dir-higher{{color:var(--success);font-size:11px;font-weight:600}}
.dir-lower{{color:var(--warning);font-size:11px;font-weight:600}}
details{{margin-bottom:24px}}
details>summary{{
    cursor:pointer;list-style:none;color:#fff;
    font-size:17px;font-weight:600;margin:20px 0 8px;
    display:flex;align-items:center;gap:8px;user-select:none
}}
details>summary::before{{content:'▶';font-size:11px;color:var(--text-dim);transition:transform .2s;display:inline-block}}
details[open]>summary::before{{transform:rotate(90deg)}}
details>summary::-webkit-details-marker{{display:none}}
[data-sort]::after{{content:' ↕';opacity:.3;font-size:10px}}
</style>
</head>
<body>
<h1>Benchmark Results Dashboard</h1>
<div class="meta">
    Run time: {timestamp} &nbsp;|&nbsp; Model: {h(model_name)}<br>
    <b>Eval composite</b>: weighted geometric mean of {len(eval_fields)} judge dimensions (sum=1.0)<br>
    <span style="opacity:.75">{h(eval_w_info)}</span><br>
    <b>Full composite</b>: weighted geometric mean of {len(all_metrics_w)} normalized RunMetrics fields (sum=1.0)
</div>

<div class="controls">
    <input type="text" id="search" placeholder="Filter by config name…" oninput="filterAll()">
    <div class="btn-group" id="filter-mode">
        <button class="active" onclick="setMode('all',this)">All</button>
        <button onclick="setMode('pass',this)">Pass</button>
        <button onclick="setMode('fail',this)">Fail</button>
    </div>
</div>

<h2>Table 1 — Winners (ranked by Eval Composite)</h2>
<table id="table-winners">
    <thead><tr>
        <th onclick="sortTable('table-winners',0)">#</th>
        <th onclick="sortTable('table-winners',1)">Config</th>
        <th onclick="sortTable('table-winners',2)">Pass</th>
        <th onclick="sortTable('table-winners',3)" data-sort>Eval Composite ↓</th>
        <th onclick="sortTable('table-winners',4)" data-sort>Full Composite</th>
        <th onclick="sortTable('table-winners',5)" data-sort>Tokens</th>
        <th onclick="sortTable('table-winners',6)" data-sort>Cost $</th>
        <th onclick="sortTable('table-winners',7)" data-sort>SPT</th>
        <th onclick="sortTable('table-winners',8)" data-sort>Avg. Tool Tokens</th>
        <th onclick="sortTable('table-winners',9)" data-sort>TTT</th>
        <th onclick="sortTable('table-winners',10)" data-sort>Waste%</th>
        <th onclick="sortTable('table-winners',11)" data-sort>Duration</th>
        <th onclick="sortTable('table-winners', 9)">Cycles</th>
        <th onclick="sortTable('table-winners', 10)">Tok/Tool</th>
        <th onclick="sortTable('table-winners', 11)">Waste%</th>
    </tr></thead>
    <tbody id="tbody-winners">{t1_rows}</tbody>
</table>

<h2>Table 2 — Full Evaluation Details</h2>
<table id="table-details">
    <thead><tr>
        <th onclick="sortTable('table-details',0)">ID</th>
        <th onclick="sortTable('table-details',1)">Config</th>
        <th onclick="sortTable('table-details',2)">Status</th>
        <th onclick="sortTable('table-details',3)">Result</th>
        <th onclick="sortTable('table-details',4)" title="In/Out/Tool/Total">Tokens</th>
        <th onclick="sortTable('table-details',5)">Cost $</th>
        <th onclick="sortTable('table-details',6)">Dur</th>
        <th onclick="sortTable('table-details',7)">M#</th>
        <th onclick="sortTable('table-details',8)">T#</th>
        <th onclick="sortTable('table-details',9)">C#</th>
        <th onclick="sortTable('table-details',10)">TTT/W%</th>
        <th onclick="sortTable('table-details',11)">Retr P/R</th>
        {eval_headers}
        <th onclick="sortTable('table-details',{comp_col_idx})" data-sort>Eval Comp</th>
        <th onclick="sortTable('table-details',{comp_col_idx+1})" data-sort>Full Comp</th>
        <th onclick="sortTable('table-details',{comp_col_idx+2})">R/W/L</th>
        <th onclick="sortTable('table-details',{comp_col_idx+3})">E/TE</th>
        <th>Cycles</th>
        <th>Tok/Tool</th>
        <th>TTT</th>
        <th>Waste%</th>
        <th>Warmup</th>
        <th onclick="sortTable('table-details',{comp_col_idx+4})">Chg</th>
    </tr></thead>
    <tbody id="tbody-details">{t2_rows}</tbody>
</table>

<details>
    <summary>Table 3 — Eval Dimensions &amp; Weights</summary>
    <table id="table-eval-weights">
        <thead><tr>
            <th>Dimension</th>
            <th>Weight (sum=1.0)</th>
            <th>Avg Score</th>
            <th>Description</th>
        </tr></thead>
        <tbody>{t3_rows}</tbody>
    </table>
</details>

<details>
    <summary>Table 4 — All-Metrics Composite Weights</summary>
    <p style="color:var(--text-dim);font-size:13px;margin:4px 0 10px">
        Weighted geometric mean across {len(all_metrics_w)} normalized RunMetrics fields (weights sum = 1.0).
        ▲ higher = higher raw value is better &nbsp;·&nbsp;
        ▼ lower = lower raw value is better (inverted: best config gets 1.0).
        Avg Norm = mean normalized score across all configs.
    </p>
    <table id="table-all-weights">
        <thead><tr>
            <th>Field</th>
            <th>Direction</th>
            <th>Weight (sum=1.0)</th>
            <th>Avg Raw</th>
            <th>Avg Norm</th>
            <th>Description</th>
        </tr></thead>
        <tbody>{t4_rows}</tbody>
    </table>
</details>

<script>
let currentMode = 'all';
function setMode(mode, btn) {{
    currentMode = mode;
    document.querySelectorAll('#filter-mode button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    filterAll();
}}
function filterAll() {{
    const q = document.getElementById('search').value.toLowerCase();
    document.querySelectorAll('#tbody-winners tr, #tbody-details tr').forEach(row => {{
        const name = row.getAttribute('data-name') || '';
        const ok = row.getAttribute('data-success') === 'true';
        const matchQ = name.includes(q);
        const matchM = currentMode === 'all' || (currentMode === 'pass' && ok) || (currentMode === 'fail' && !ok);
        row.style.display = matchQ && matchM ? '' : 'none';
    }});
}}
function sortTable(tableId, col) {{
    const tbl = document.getElementById(tableId);
    const tbody = tbl.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const asc = tbl.getAttribute('data-sort-dir') !== 'asc';
    rows.sort((a, b) => {{
        let va = a.cells[col].getAttribute('data-val') || a.cells[col].textContent;
        let vb = b.cells[col].getAttribute('data-val') || b.cells[col].textContent;
        if (!isNaN(parseFloat(va)) && !isNaN(parseFloat(vb)))
            return asc ? parseFloat(va) - parseFloat(vb) : parseFloat(vb) - parseFloat(va);
        return asc ? va.localeCompare(vb) : vb.localeCompare(va);
    }});
    rows.forEach(r => tbody.appendChild(r));
    tbl.setAttribute('data-sort-dir', asc ? 'asc' : 'desc');
}}
</script>
</body>
</html>"""


def _build_dashboard():
    pass
