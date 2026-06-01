# Plan: Fix streamlit_app.py KeyError on missing columns

## Problem
Old metrics.json files (from benchmark runs before ROADMAP_V2) don't have fields:
`time_to_target`, `context_waste_ratio`, `agent_cycles`, `avg_tokens_per_tool`, `warmup_sec`

The streamlit app crashes with:
  KeyError: "['time_to_target', 'context_waste_ratio'] not in index"

on this line:
```python
leaderboard_df = filtered_df[[
    'config_id_full', 'success', 'eval_score', 'total_tokens', 'cost_usd',
    'success_per_token', 'time_to_target', 'context_waste_ratio'
]].copy()
```

## Fix: streamlit_app.py

File: `streamlit_app.py`

### Fix 1: After `load_data()` call, fill missing columns with defaults

After `df = load_data()` and before the `if df.empty:` check, add:

```python
# Backfill columns that may be absent in metrics from old benchmark runs
_NEW_FLOAT_COLS = ['time_to_target', 'context_waste_ratio', 'avg_tokens_per_tool', 'warmup_sec']
_NEW_INT_COLS = ['agent_cycles']
_COMPAT_COLS = {
    'success_per_token': 0.0,
    'total_tokens': 0,
    'cost_usd': 0.0,
}
for col in _NEW_FLOAT_COLS:
    if col not in df.columns:
        df[col] = 0.0
for col in _NEW_INT_COLS:
    if col not in df.columns:
        df[col] = 0
for col, default in _COMPAT_COLS.items():
    if col not in df.columns:
        df[col] = default
```

### Fix 2: Tab 2 — guard against missing judge score columns

In Tab 2, the `judge_dims` dict uses `.get()` on a pandas Series (config_data) with a fallback.
This works but ONLY if the column exists in the dataframe. If filtered_df doesn't have these columns,
`config_data.get(k, 0)` will still fail with KeyError.

Add judge score columns backfill in the same block above:
```python
_JUDGE_COLS = [
    'task_solved_score', 'correctness_score', 'tool_correctness_score',
    'context_quality_score', 'minimality_score', 'pattern_adherence_score',
    'tool_sequence_score',
]
for col in _JUDGE_COLS:
    if col not in df.columns:
        df[col] = 0.0
```

### Fix 3: Tab 2 — median_dims KeyError guard

Current code:
```python
median_dims = {k: filtered_df[k].median() for k in judge_dims.keys()}
```
This will KeyError if a judge column is missing. The backfill above fixes this, but add a safe fallback anyway:
```python
median_dims = {k: filtered_df[k].median() if k in filtered_df.columns else 0.0 for k in judge_dims.keys()}
```

### Fix 4: Tab 2 — agent_messages may not be a list

The agent timeline iterates `config_data['agent_messages']`. This column may contain `NaN` for
old runs that didn't save agent_messages.json.

Replace:
```python
for msg in config_data['agent_messages']:
```
With:
```python
messages = config_data.get('agent_messages', [])
if not isinstance(messages, list):
    messages = []
for msg in messages:
```

### Fix 5: Tab 2 — final_patch may be NaN

Replace:
```python
st.code(config_data['final_patch'], language='diff')
```
With:
```python
patch_content = config_data.get('final_patch', '')
if not isinstance(patch_content, str):
    patch_content = "No patch file available for this run."
st.code(patch_content, language='diff')
```

## Implementation note
All fixes are in `streamlit_app.py` only. No other files to change.
The backfill block (Fixes 1 + 2) is the most important — place it right after `df = load_data()`.
