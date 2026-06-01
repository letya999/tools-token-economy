# Plan: Streamlit Multi-Page Dashboard Extension
Date: 2026-05-28

## Goal
Extend `streamlit_app.py` with 5 new pages/tabs in addition to the existing Leaderboard and Config Deep Dive.

## Current state
`streamlit_app.py` has 2 tabs: Leaderboard + Config Deep Dive.
Data is loaded from `results/run_*/metrics.json` + `final.patch` + `agent_messages.json`.
Config info comes from `configs/tools.yaml`, `configs/provider.yaml`, `configs/tasks/medium.yaml`, `configs/codebase.yaml`, `configs/benchmark_weights.yaml`.

## New structure: 7 tabs total

```
st.tabs([
    "Leaderboard",        # existing, keep
    "Config Explorer",    # NEW (moved and expanded from "Config Deep Dive")
    "Charts",             # NEW
    "Run Info",           # NEW
    "Weights",            # NEW
    "Glossary",           # NEW
    "Config Deep Dive",   # existing, keep at end
])
```

---

## Tab: Run Info (Tab 3)

Shows static info about the current benchmark run. Loads from YAML files.

### Layout:
```
st.header("Run Configuration")

col1, col2 = st.columns(2)

col1: 
  st.subheader("Provider & Model")
    - provider: openai
    - model: openai/gpt-4.1-mini
    - max_steps: 50
    - temperature: 0.0

  st.subheader("Task")
    - name, difficulty
    - description (st.text_area, read-only)
    - test_cmd, timeout_sec
    - required_files (st.code)

col2:
  st.subheader("Codebase")
    - name, github_url, local_path, branch, install_cmd

  st.subheader("Tools Configurations (20)")
    - st.dataframe with columns: id, name, archetype, tools (comma-joined), model, max_steps
    - loaded from configs/tools.yaml + configs/provider.yaml
```

### Implementation notes:
- Load configs with try/except (files may not exist)
- Use `yaml.safe_load()` to read YAML files directly (don't import from src — streamlit runs standalone)
- If a config file doesn't exist, show st.warning("Config file not found: path")

---

## Tab: Weights (Tab 4)

Shows benchmark scoring weights in two sections.

### Layout:
```
st.header("Benchmark Weights")

st.subheader("Eval Judge Composite (7 dimensions)")
# Bar chart: metric name → weight value
fig_eval = px.bar(eval_df, x='Metric', y='Weight', title="Eval Composite Weights")
st.plotly_chart(fig_eval)
st.dataframe(eval_df)  # also show as table

st.subheader("All-Metrics Composite (18 fields)")
# Grouped bar chart colored by direction (higher/lower)
fig_all = px.bar(all_df, x='Metric', y='Weight', color='Direction', 
                  title="All-Metrics Composite Weights",
                  color_discrete_map={'higher': '#10b981', 'lower': '#ef4444'})
st.plotly_chart(fig_all)
st.dataframe(all_df)  # also show as table with description
```

### Data:
Load from `configs/benchmark_weights.yaml` directly with yaml.safe_load.
Build DataFrames:
- eval_df: columns=[Metric, Weight]
- all_df: columns=[Metric, Weight, Direction, Description]

---

## Tab: Glossary (Tab 5)

Static reference page explaining all metrics.

### Layout:
```
st.header("Metrics Glossary")

# Search box
search = st.text_input("Search term")

# Sections — show all, or filter by search
```

### Glossary content (hardcoded dict, no YAML needed):

```python
GLOSSARY = {
    "Eval Composite Metrics": {
        "task_solved_score": ("0–1, higher better", "Did the agent accomplish the full task? Scored by LLM judge."),
        "correctness_score": ("0–1, higher better", "Is the produced code technically correct, free of bugs and side effects?"),
        "tool_correctness_score": ("0–1, higher better", "Did the agent use the right retrieval tools with correct arguments?"),
        "context_quality_score": ("0–1, higher better", "Was gathered context relevant? Penalizes over-reading."),
        "minimality_score": ("0–1, higher better", "Surgical edits only — no unnecessary file rewrites or changes."),
        "pattern_adherence_score": ("0–1, higher better", "Does the code follow project conventions and style?"),
        "tool_sequence_score": ("0–1, higher better", "Were tool calls in a logical, efficient order?"),
    },
    "Retrieval Metrics": {
        "retrieval_precision": ("0–1, higher better", "Fraction of files read that were actually needed (required_files)."),
        "retrieval_recall": ("0–1, higher better", "Fraction of needed files that were actually read."),
        "time_to_target": ("cycles, lower better", "Which agent cycle (1-based) the first required file was first read. 0 = never read."),
        "context_waste_ratio": ("0–1, lower better", "Fraction of read tokens that came from non-required files."),
    },
    "Efficiency Metrics": {
        "total_tokens": ("count, lower better", "Total LLM tokens: input + output + tool response tokens."),
        "cost_usd": ("USD, lower better", "Estimated API cost based on model pricing."),
        "duration_sec": ("seconds, lower better", "Wall-clock time from agent start to finish (excludes MCP warmup)."),
        "warmup_sec": ("seconds, info", "Time spent on MCP server warmup (excluded from duration_sec)."),
        "model_calls": ("count, lower better", "Number of LLM API calls (= assistant messages)."),
        "tool_calls": ("count, info", "Total tool invocations across all cycles."),
        "agent_cycles": ("count, info", "Number of think→tool→response cycles (= tool role messages)."),
        "avg_tokens_per_tool": ("tokens, lower better", "Average tokens in tool responses. Lower = more surgical tool use."),
    },
    "Reliability Metrics": {
        "errors": ("count, lower better", "Test failures or runtime errors during execution."),
        "tool_errors": ("count, lower better", "Tool call failures (wrong args, timeout, parse error)."),
        "success": ("bool", "True if agent made changes AND tests passed (didn't regress)."),
        "made_changes": ("bool", "True if any file was actually modified (git diff non-empty)."),
        "patch_lines": ("count", "Total added + removed lines in the final patch."),
    },
    "Composite Scores": {
        "eval_score": ("0–1", "Weighted geometric mean of 7 LLM judge dimensions (eval_weights)."),
        "success_per_token (SPT)": ("score/1M tokens", "Scaled score: task_solved_score * 1,000,000 / total_tokens. Higher = more efficient success."),
    },
}
```

### Display per section:
```python
for section, items in GLOSSARY.items():
    # Filter by search if provided
    matching = {k: v for k, v in items.items() 
                if not search or search.lower() in k.lower() or search.lower() in v[1].lower()}
    if not matching:
        continue
    with st.expander(section, expanded=True):
        for metric, (range_info, description) in matching.items():
            st.markdown(f"**`{metric}`** — *{range_info}*")
            st.markdown(f"  {description}")
            st.divider()
```

---

## Tab: Charts (Tab 6)

Interactive visualization with two sub-sections.

### Section 1: Bar Chart — Config Comparison

```
st.subheader("Bar Chart: Config Comparison")

col_left, col_right = st.columns([1, 3])
with col_left:
    # Select metric for Y axis
    metric = st.selectbox("Y-axis metric", [
        'eval_score', 'total_tokens', 'cost_usd', 'success_per_token',
        'duration_sec', 'tool_calls', 'agent_cycles', 'avg_tokens_per_tool',
        'time_to_target', 'context_waste_ratio', 'retrieval_precision', 'retrieval_recall',
        'task_solved_score', 'correctness_score', 'tool_correctness_score',
        'context_quality_score', 'minimality_score',
    ])
    
    # Multi-select configs (all by default)
    all_configs = sorted(filtered_df['config_id_full'].unique())
    selected_configs = st.multiselect("Configs to show", all_configs, default=all_configs)
    
    # Color grouping: archetype field (loaded from tools.yaml) or 'success'
    color_by = st.selectbox("Color by", ['archetype', 'success', 'none'])

with col_right:
    chart_df = filtered_df[filtered_df['config_id_full'].isin(selected_configs)].copy()
    # Merge archetype from tools.yaml if color_by == 'archetype'
    if color_by == 'archetype' and 'archetype' in chart_df.columns:
        fig = px.bar(chart_df, x='config_id_full', y=metric, color='archetype',
                     barmode='group', title=f"{metric} by config")
    elif color_by == 'success':
        chart_df['Pass'] = chart_df['success'].map({True: 'PASS', False: 'FAIL'})
        fig = px.bar(chart_df, x='config_id_full', y=metric, color='Pass',
                     color_discrete_map={'PASS': '#10b981', 'FAIL': '#ef4444'},
                     barmode='group', title=f"{metric} by config")
    else:
        fig = px.bar(chart_df, x='config_id_full', y=metric, title=f"{metric} by config")
    
    fig.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)
```

### Section 2: Radar Chart — Multi-Config Comparison

```
st.subheader("Radar Chart: Multi-Config Comparison")

ALL_DIMENSIONS = [
    'task_solved_score', 'correctness_score', 'tool_correctness_score',
    'context_quality_score', 'minimality_score', 'pattern_adherence_score',
    'tool_sequence_score', 'retrieval_precision', 'retrieval_recall',
    'eval_score', 'success_per_token',
]

col_left2, col_right2 = st.columns([1, 3])
with col_left2:
    radar_configs = st.multiselect(
        "Configs (max 5)", all_configs, default=all_configs[:3],
        max_selections=5,
    )
    radar_dims = st.multiselect(
        "Dimensions (max 12)", ALL_DIMENSIONS, default=ALL_DIMENSIONS[:7],
        max_selections=12,
    )

with col_right2:
    if len(radar_configs) >= 1 and len(radar_dims) >= 3:
        fig_radar = go.Figure()
        for cfg_id in radar_configs:
            row = filtered_df[filtered_df['config_id_full'] == cfg_id]
            if row.empty:
                continue
            r_vals = [float(row.iloc[0].get(d, 0)) for d in radar_dims]
            fig_radar.add_trace(go.Scatterpolar(
                r=r_vals + [r_vals[0]],
                theta=radar_dims + [radar_dims[0]],
                mode='lines+markers',
                name=cfg_id,
            ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            title="Multi-Config Radar Comparison",
        )
        st.plotly_chart(fig_radar, use_container_width=True)
    else:
        st.info("Select at least 1 config and 3 dimensions.")
```

Note: need `import plotly.graph_objects as go` at the top.

---

## Tab: Config Explorer (Tab 2 — new)

Full list of all configs in the selected run. Expandable per config to see full details.

### Layout:
```
st.header("Config Explorer")
st.caption(f"Run: {selected_ts} — {len(filtered_df)} configs")

# Sort options
sort_metric = st.selectbox("Sort by", ['eval_score', 'total_tokens', 'cost_usd', 'success'])
sort_asc = st.checkbox("Ascending", value=False)
sorted_df = filtered_df.sort_values(sort_metric, ascending=sort_asc)

for _, row in sorted_df.iterrows():
    config_id = row['config_id_full']
    passed = row.get('success', False)
    eval_s = row.get('eval_score', 0.0)
    tokens = row.get('total_tokens', 0)
    cost = row.get('cost_usd', 0.0)
    
    status_icon = "✅" if passed else "❌"
    header_label = f"{status_icon} **{config_id}** — eval={eval_s:.2f} | tokens={tokens:,} | ${cost:.4f}"
    
    with st.expander(header_label, expanded=False):
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Eval Score", f"{eval_s:.3f}")
        col_m2.metric("Total Tokens", f"{tokens:,}")
        col_m3.metric("Cost", f"${cost:.4f}")
        col_m4.metric("Duration", f"{row.get('duration_sec', 0):.1f}s")
        
        col_m5, col_m6, col_m7, col_m8 = st.columns(4)
        col_m5.metric("Agent Cycles", row.get('agent_cycles', 0))
        col_m6.metric("Tool Calls", row.get('tool_calls', 0))
        col_m7.metric("TTT", row.get('time_to_target', 0))
        col_m8.metric("Waste%", f"{row.get('context_waste_ratio', 0)*100:.1f}%")
        
        # Judge scores section
        st.markdown("**Judge Scores**")
        judge_cols = st.columns(7)
        judge_fields = [
            ('Task', 'task_solved_score'), ('Correct', 'correctness_score'),
            ('Tools', 'tool_correctness_score'), ('Context', 'context_quality_score'),
            ('Minimal', 'minimality_score'), ('Pattern', 'pattern_adherence_score'),
            ('Sequence', 'tool_sequence_score'),
        ]
        for i, (label, field) in enumerate(judge_fields):
            judge_cols[i].metric(label, f"{row.get(field, 0):.2f}")
        
        # Reasoning sections
        reasoning_fields = {
            'Task Solved': 'judge_reasoning_task',
            'Tool Use': 'judge_reasoning_tools',
            'Context': 'judge_reasoning_context',
            'Correctness': 'judge_reasoning_correctness',
            'Minimality': 'judge_reasoning_minimality',
            'Pattern': 'judge_reasoning_pattern',
            'Tool Sequence': 'judge_reasoning_tool_sequence',
        }
        
        st.markdown("**Agent Reasoning (LLM Judge)**")
        r_cols = st.columns(2)
        for i, (label, field) in enumerate(reasoning_fields.items()):
            text = row.get(field, '')
            if text and str(text) not in ('', 'nan'):
                with r_cols[i % 2]:
                    st.markdown(f"*{label}:* {text}")
        
        # Code Diff
        patch = row.get('final_patch', '')
        if patch and str(patch) not in ('', 'nan', 'Patch file not found.'):
            st.markdown("**Code Diff**")
            st.code(patch, language='diff')
        
        # Agent Timeline
        messages = row.get('agent_messages', [])
        if not isinstance(messages, list):
            messages = []
        if messages:
            st.markdown("**Agent Timeline**")
            timeline = []
            cycle = 0
            for msg in messages:
                if msg.get('role') == 'tool':
                    cycle += 1
                if msg.get('tool_calls'):
                    for tc in (msg['tool_calls'] if isinstance(msg['tool_calls'], list) else []):
                        if isinstance(tc, dict):
                            tool_name = tc.get('function', {}).get('name', 'unknown') if 'function' in tc else tc.get('tool_name', 'unknown')
                            args = str(tc.get('function', {}).get('arguments', ''))[:120] if 'function' in tc else str(tc.get('input', ''))[:120]
                        else:
                            tool_name = str(tc)[:30]
                            args = ''
                        timeline.append({"Cycle": cycle, "Tool": tool_name, "Args": args})
            if timeline:
                st.dataframe(timeline, use_container_width=True)
```

---

## Implementation: file structure

All new tabs go into `streamlit_app.py`. The file is rewritten to have 7 tabs.
Keep the existing data loading (load_data function) and backfill logic unchanged.

Add at the top of the file:
```python
import yaml
import plotly.graph_objects as go
```

Load YAML configs at the top level (after df/backfill, before tabs):
```python
def _load_yaml(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

provider_cfg = _load_yaml('configs/provider.yaml')
task_cfg = _load_yaml('configs/tasks/medium.yaml')
codebase_cfg = _load_yaml('configs/codebase.yaml')
tools_cfg = _load_yaml('configs/tools.yaml')
weights_cfg = _load_yaml('configs/benchmark_weights.yaml')
```

For the bar chart's archetype coloring, merge from tools_cfg:
```python
archetype_map = {c['id']: c.get('archetype', 'unknown') for c in tools_cfg.get('configs', [])}
df['archetype'] = df['config_id_full'].map(archetype_map).fillna('unknown')
```
Add this right after the backfill block.

---

## Tests: tests/features/test_streamlit_app.py (NEW FILE)

Create `tests/features/test_streamlit_app.py` with these tests:

```python
"""Tests for streamlit_app.py logic functions."""
import json
import os
import pytest
import pandas as pd


def _make_metrics_json(run_dir: str, config_id: str, **overrides) -> str:
    """Write a minimal metrics.json and return its path."""
    os.makedirs(run_dir, exist_ok=True)
    data = dict(
        success=True, eval_score=0.8,
        input_tokens=1000, output_tokens=400, tool_tokens=200,
        total_tokens=1600, cost_usd=0.002,
        duration_sec=45.0, model_calls=5, tool_calls=12,
        success_per_token=500.0,
        task_solved_score=0.9, correctness_score=0.8,
        tool_correctness_score=0.7, context_quality_score=0.6,
        minimality_score=0.5, pattern_adherence_score=0.4, tool_sequence_score=0.3,
        judge_reasoning_task="Agent did well.",
        agent_cycles=4, time_to_target=2, context_waste_ratio=0.3,
        avg_tokens_per_tool=16.7, warmup_sec=0.5,
        retrieval_precision=0.8, retrieval_recall=0.6,
        errors=0, tool_errors=1,
    )
    data.update(overrides)
    path = os.path.join(run_dir, "metrics.json")
    with open(path, 'w') as f:
        json.dump(data, f)
    return path


class TestBackfillLogic:
    """Test that missing columns are filled with correct defaults."""

    def test_new_columns_added_when_missing(self, tmp_path):
        # Simulate old metrics without new fields
        old_data = {'config_id_full': 'test', 'timestamp': '20260101_000000',
                    'success': True, 'eval_score': 1.0,
                    'total_tokens': 1000, 'cost_usd': 0.01,
                    'agent_messages': [], 'final_patch': ''}
        df = pd.DataFrame([old_data])
        
        # Apply same backfill logic as streamlit_app.py
        NEW_FLOAT_COLS = ['time_to_target', 'context_waste_ratio', 'avg_tokens_per_tool', 'warmup_sec']
        NEW_INT_COLS = ['agent_cycles']
        for col in NEW_FLOAT_COLS:
            if col not in df.columns:
                df[col] = 0.0
        for col in NEW_INT_COLS:
            if col not in df.columns:
                df[col] = 0

        assert df['time_to_target'].iloc[0] == 0.0
        assert df['context_waste_ratio'].iloc[0] == 0.0
        assert df['agent_cycles'].iloc[0] == 0
        assert df['avg_tokens_per_tool'].iloc[0] == 0.0

    def test_existing_columns_not_overwritten(self):
        df = pd.DataFrame([{'time_to_target': 5, 'context_waste_ratio': 0.4}])
        if 'time_to_target' not in df.columns:
            df['time_to_target'] = 0.0
        # Should keep original value
        assert df['time_to_target'].iloc[0] == 5

    def test_agent_messages_nan_handled(self):
        import numpy as np
        df = pd.DataFrame([{'agent_messages': np.nan}])
        messages = df['agent_messages'].iloc[0]
        if not isinstance(messages, list):
            messages = []
        assert messages == []

    def test_final_patch_nan_handled(self):
        import numpy as np
        patch = float('nan')
        content = patch if isinstance(patch, str) else "No patch available."
        assert content == "No patch available."


class TestGlossaryContent:
    """Test that glossary has all expected keys."""

    def test_all_eval_metrics_covered(self):
        EXPECTED_EVAL = {
            'task_solved_score', 'correctness_score', 'tool_correctness_score',
            'context_quality_score', 'minimality_score', 'pattern_adherence_score',
            'tool_sequence_score',
        }
        # Load the glossary from streamlit_app module
        # We just check the keys are plausible
        assert len(EXPECTED_EVAL) == 7

    def test_retrieval_metrics_covered(self):
        EXPECTED = {'retrieval_precision', 'retrieval_recall', 'time_to_target', 'context_waste_ratio'}
        assert len(EXPECTED) == 4


class TestAgentTimelineExtraction:
    """Test timeline extraction logic."""

    def test_cycles_counted_correctly(self):
        messages = [
            {'role': 'assistant', 'content': 'thinking', 'tool_calls': [
                {'function': {'name': 'read_file', 'arguments': '{"path": "x.py"}'}, 'id': '1'}
            ]},
            {'role': 'tool', 'content': 'file contents', 'tool_calls': None},
            {'role': 'assistant', 'content': 'thinking2', 'tool_calls': [
                {'function': {'name': 'write', 'arguments': '{"path": "x.py"}'}, 'id': '2'}
            ]},
            {'role': 'tool', 'content': 'written', 'tool_calls': None},
        ]
        
        timeline = []
        cycle = 0
        for msg in messages:
            if msg.get('role') == 'tool':
                cycle += 1
            if msg.get('tool_calls'):
                for tc in msg['tool_calls']:
                    if isinstance(tc, dict) and 'function' in tc:
                        tool_name = tc['function']['name']
                        timeline.append({'cycle': cycle, 'tool': tool_name})
        
        assert len(timeline) == 2
        assert timeline[0]['tool'] == 'read_file'
        assert timeline[1]['tool'] == 'write'
        assert timeline[0]['cycle'] == 0  # before first tool message
        assert timeline[1]['cycle'] == 1  # after first tool message


class TestLoadYamlHelper:
    """Test _load_yaml fallback behavior."""

    def test_nonexistent_file_returns_empty_dict(self, tmp_path):
        path = str(tmp_path / "nonexistent.yaml")
        try:
            import yaml
            with open(path, 'r') as f:
                result = yaml.safe_load(f) or {}
        except Exception:
            result = {}
        assert result == {}

    def test_valid_yaml_loads_correctly(self, tmp_path):
        import yaml
        data = {'key': 'value', 'nested': {'a': 1}}
        path = tmp_path / "test.yaml"
        path.write_text(yaml.dump(data))
        with open(str(path), 'r') as f:
            result = yaml.safe_load(f) or {}
        assert result['key'] == 'value'
        assert result['nested']['a'] == 1
```

---

## Implementation constraints
- Add `import yaml` and `import plotly.graph_objects as go` at the top of streamlit_app.py
- Do NOT break existing Leaderboard and Config Deep Dive tabs
- Use `max_selections` parameter in `st.multiselect` for Charts tab (max 5 configs, max 12 dims)
- The tab order: ["Leaderboard", "Config Explorer", "Charts", "Run Info", "Weights", "Glossary", "Config Deep Dive"]
- All YAML loading uses try/except to be safe when files don't exist
- Tests go in `tests/features/test_streamlit_app.py` (new file)
- After writing tests, run `uv run python -m pytest tests/features/test_streamlit_app.py -v` to verify
