"""Benchmark Dashboard — Streamlit app.

Launch:
    uv run streamlit run streamlit_app.py

All config paths are resolved relative to this file so the app works
regardless of the working directory from which Streamlit is invoked.
"""
import json
import os
import glob as _glob
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml
from src.features.multi_run import list_sessions, aggregate_session
from src.features.significance import rank_with_tiebands, partition_by_status
from src.features.stats import STATUS_OK, STATUS_LOW_CONFIDENCE

# ── Project root (absolute, independent of CWD) ───────────────────────────────
_ROOT = Path(__file__).parent


# ── i18n ─────────────────────────────────────────────────────────────────────

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # page
        "page_title": "Benchmark Dashboard",
        "app_title": "Benchmark Dashboard",
        # sidebar
        "sidebar_title": "Filters",
        "run_timestamp": "Run Timestamp",
        "status_label": "Status",
        "status_all": "All",
        "status_pass": "Pass Only",
        "status_fail": "Fail Only",
        "configs_in_view": "Configs in view",
        "pass_rate": "Pass rate",
        "language": "Language",
        # tabs
        "tab_leaderboard": "Leaderboard",
        "tab_explorer": "Config Explorer",
        "tab_charts": "Charts",
        "tab_run_info": "Run Info",
        "tab_weights": "Weights",
        "tab_glossary": "Glossary",
        "tab_deep_dive": "Config Deep Dive",
        "tab_all_metrics": "All Metrics",
        # common
        "no_data": "No data for selected filters.",
        "no_data_run": "No data found in results/. Run the benchmark first.",
        "sort_by": "Sort by",
        "ascending": "Ascending",
        "select_config": "Select config",
        "search_placeholder": "Search metric name or description",
        "ranked_results": "Ranked Results (Significance-Aware)",
        "not_ranked_results": "Not Ranked (Unstable / Insufficient Data)",
        "single_run_warning": "⚠️ **SINGLE RUN SESSION** — Results lack statistical significance. Run with `--runs 5` or more.",
        "download_csv": "📥 Download Aggregated Results (CSV)",
        "judge_calls": "Judge Calls",
        "judge_calls_header": "Вызовы судьи / Judge Calls",
        "terminology_header": "Терминология / Terminology",
        "col_rank": "Rank",
        "col_band": "Band",
        "col_status": "Status",
        "col_runs": "Runs",
        "stat_summary": "Statistical Summary",
        "spt_zero_warning": "⚠️ All configurations failed the task or judge did not run.",
        # leaderboard
        "leaderboard_header": "Leaderboard",
        "col_config": "Config",
        "col_pass": "Pass",
        "col_eval": "Eval",
        "col_tokens": "Tokens",
        "col_cost": "Cost $",
        "col_spt": "SPT",
        "col_ttt": "TTT",
        "col_waste": "Waste%",
        "col_cycles": "Cycles",
        # explorer
        "explorer_header": "Config Explorer",
        "explorer_caption": "Run {ts} — {n} configs",
        "judge_scores": "Judge Scores",
        "judge_reasoning": "LLM Judge Reasoning",
        "code_diff": "Code Diff",
        "agent_timeline": "Agent Timeline",
        "no_reasoning": "No judge reasoning available.",
        "no_patch": "No patch available.",
        "no_messages": "No agent messages available.",
        "no_tool_calls": "No tool calls recorded.",
        "metric_eval": "Eval",
        "metric_tokens": "Tokens",
        "metric_cost": "Cost",
        "metric_duration": "Duration",
        "metric_cycles": "Cycles",
        "metric_tool_calls": "Tool calls",
        "metric_ttt": "TTT",
        "metric_waste": "Waste%",
        # charts
        "bar_chart_header": "Bar Chart: Config Comparison",
        "y_axis_metric": "Y-axis metric",
        "configs_to_show": "Configs to show",
        "color_by": "Color by",
        "radar_header": "Radar Chart: Multi-Config Comparison",
        "configs_max5": "Configs (max 5)",
        "dims_max12": "Dimensions (max 12)",
        "radar_hint": "Select ≥1 config and ≥3 dimensions.",
        # run info
        "run_info_header": "Run Configuration",
        "provider_model": "Provider & Model",
        "task_label": "Task",
        "task_name": "Name",
        "task_difficulty": "Difficulty",
        "task_description": "Description",
        "task_test_cmd": "Test Command",
        "task_timeout": "Timeout",
        "task_required_files": "Required Files",
        "codebase_label": "Codebase",
        "tools_configs": "Tools Configs",
        "not_found": "not found",
        # weights
        "weights_header": "Benchmark Weights",
        "eval_composite_header": "Eval Judge Composite (7 dimensions)",
        "eval_composite_caption": "Weighted geometric mean of 7 LLM-judge scores. Weights must sum to 1.0.",
        "eval_composite_chart": "Eval Composite Weights",
        "all_metrics_header": "All-Metrics Composite (18 fields)",
        "all_metrics_caption": "Weighted geometric mean over all RunMetrics fields. Weights sum to 1.0.",
        "all_metrics_chart": "All-Metrics Composite Weights",
        "col_metric": "Metric",
        "col_weight": "Weight",
        "col_direction": "Direction",
        "col_description": "Description",
        # glossary
        "glossary_header": "Metrics & Scoring Glossary",
        "glossary_caption": "Complete reference for every metric, eval score, and indicator shown in the benchmark tables.",
        "glossary_shown_in": "Shown in",
        "glossary_no_results": "No metrics match '{q}'.",
        # all metrics
        "all_metrics_tab_header": "All Metrics — Complete View",
        "all_metrics_tab_caption": "Every single RunMetrics field for every config in the selected run, side-by-side.",
        # deep dive
        "deep_dive_header": "Configuration Deep Dive",
        "judge_dims_vs_median": "Judge Dimensions vs Median",
        "no_reasoning_deep": "No reasoning available.",
        "no_patch_deep": "No patch.",
    },
    "ru": {
        # page
        "page_title": "Бенчмарк Дашборд",
        "app_title": "Бенчмарк Дашборд",
        # sidebar
        "sidebar_title": "Фильтры",
        "run_timestamp": "Временная метка",
        "status_label": "Статус",
        "status_all": "Все",
        "status_pass": "Только успех",
        "status_fail": "Только провал",
        "configs_in_view": "Конфигов",
        "pass_rate": "Успех",
        "language": "Язык",
        # tabs
        "tab_leaderboard": "Лидерборд",
        "tab_explorer": "Обзор конфигов",
        "tab_charts": "Графики",
        "tab_run_info": "Инфо о запуске",
        "tab_weights": "Веса",
        "tab_glossary": "Глоссарий",
        "tab_deep_dive": "Детальный разбор",
        "tab_all_metrics": "Все метрики",
        # common
        "no_data": "Нет данных для выбранных фильтров.",
        "no_data_run": "Нет данных в results/. Сначала запустите бенчмарк.",
        "sort_by": "Сортировать по",
        "ascending": "По возрастанию",
        "select_config": "Выбрать конфиг",
        "search_placeholder": "Поиск по названию или описанию метрики",
        "ranked_results": "Ранжированные результаты (с учётом значимости)",
        "not_ranked_results": "Не ранжированы (нестабильные / недостаточно данных)",
        "single_run_warning": "⚠️ **SINGLE RUN SESSION** — Результаты не имеют статистической значимости. Запустите с `--runs 5` или более.",
        "download_csv": "📥 Скачать агрегированные результаты (CSV)",
        "judge_calls": "Вызовы судьи",
        "judge_calls_header": "Вызовы судьи / Judge Calls",
        "terminology_header": "Терминология / Terminology",
        "col_rank": "Место",
        "col_band": "Группа",
        "col_status": "Статус",
        "col_runs": "Ранов",
        "stat_summary": "Статистическая сводка",
        "spt_zero_warning": "⚠️ Все конфигурации не решили задачу или судья не запускался.",
        # leaderboard
        "leaderboard_header": "Таблица лидеров",
        "col_config": "Конфиг",
        "col_pass": "Успех",
        "col_eval": "Eval",
        "col_tokens": "Токены",
        "col_cost": "Стоимость $",
        "col_spt": "SPT",
        "col_ttt": "TTT",
        "col_waste": "Отход%",
        "col_cycles": "Циклы",
        # explorer
        "explorer_header": "Обзор конфигов",
        "explorer_caption": "Запуск {ts} — {n} конфигов",
        "judge_scores": "Оценки судьи",
        "judge_reasoning": "Рассуждения LLM-судьи",
        "code_diff": "Код (diff)",
        "agent_timeline": "Хронология агента",
        "no_reasoning": "Рассуждения судьи недоступны.",
        "no_patch": "Патч недоступен.",
        "no_messages": "Сообщения агента недоступны.",
        "no_tool_calls": "Вызовы инструментов не записаны.",
        "metric_eval": "Eval",
        "metric_tokens": "Токены",
        "metric_cost": "Стоимость",
        "metric_duration": "Время",
        "metric_cycles": "Циклы",
        "metric_tool_calls": "Вызовы инстр.",
        "metric_ttt": "TTT",
        "metric_waste": "Отход%",
        # charts
        "bar_chart_header": "Столбчатая диаграмма: сравнение конфигов",
        "y_axis_metric": "Метрика (ось Y)",
        "configs_to_show": "Конфиги для отображения",
        "color_by": "Раскраска",
        "radar_header": "Радарная диаграмма: сравнение конфигов",
        "configs_max5": "Конфиги (макс. 5)",
        "dims_max12": "Дименшны (макс. 12)",
        "radar_hint": "Выберите ≥1 конфиг и ≥3 дименшна.",
        # run info
        "run_info_header": "Конфигурация запуска",
        "provider_model": "Провайдер и модель",
        "task_label": "Задача",
        "task_name": "Название",
        "task_difficulty": "Сложность",
        "task_description": "Описание",
        "task_test_cmd": "Команда тестирования",
        "task_timeout": "Таймаут",
        "task_required_files": "Требуемые файлы",
        "codebase_label": "Кодовая база",
        "tools_configs": "Конфиги инструментов",
        "not_found": "не найден",
        # weights
        "weights_header": "Веса бенчмарка",
        "eval_composite_header": "Eval Judge Composite (7 измерений)",
        "eval_composite_caption": "Взвешенное геометрическое среднее 7 оценок LLM-судьи. Сумма весов = 1.0.",
        "eval_composite_chart": "Веса Eval Composite",
        "all_metrics_header": "All-Metrics Composite (18 полей)",
        "all_metrics_caption": "Взвешенное геометрическое среднее по всем полям RunMetrics. Сумма весов = 1.0.",
        "all_metrics_chart": "Веса All-Metrics Composite",
        "col_metric": "Метрика",
        "col_weight": "Вес",
        "col_direction": "Направление",
        "col_description": "Описание",
        # glossary
        "glossary_header": "Глоссарий метрик и оценок",
        "glossary_caption": "Полный справочник по каждой метрике, eval-оценке и показателю в таблицах бенчмарка.",
        "glossary_shown_in": "Показывается в",
        "glossary_no_results": "Метрики по запросу '{q}' не найдены.",
        # all metrics
        "all_metrics_tab_header": "Все метрики — полный вид",
        "all_metrics_tab_caption": "Все поля RunMetrics по каждому конфигу выбранного запуска.",
        # deep dive
        "deep_dive_header": "Детальный разбор конфига",
        "judge_dims_vs_median": "Дименшны судьи vs медиана",
        "no_reasoning_deep": "Рассуждения недоступны.",
        "no_patch_deep": "Патч недоступен.",
    },
}

_column_names = {
    "en": {
        "rank": "Rank", "tie_band": "Band", "config_name": "Config",
        "_validity_status": "Status", "n_runs_completed": "Runs",
        "eval_score": "Eval", "total_tokens": "Tokens", "cost_usd": "Cost $",
        "net_spt": "SPT",
    },
    "ru": {
        "rank": "Место", "tie_band": "Группа", "config_name": "Конфигурация",
        "_validity_status": "Статус", "n_runs_completed": "Ранов",
        "eval_score": "Оценка", "total_tokens": "Токены", "cost_usd": "Стоимость $",
        "net_spt": "SPT",
    }
}

_STATUS_MAP = {
    "en": {"ok": "ok", "low_confidence": "low confidence", "unstable": "unstable", "insufficient_data": "insufficient data"},
    "ru": {"ok": "норма", "low_confidence": "низкая уверенность", "unstable": "нестабильно", "insufficient_data": "мало данных"}
}



def _t(key: str, **kwargs) -> str:
    """Return localised string for current language."""
    lang = st.session_state.get("lang", "en")
    s = _STRINGS.get(lang, _STRINGS["en"]).get(key, _STRINGS["en"].get(key, key))
    return s.format(**kwargs) if kwargs else s


# ── Config (absolute paths) ───────────────────────────────────────────────────

def _load_yaml(rel: str) -> dict:
    path = _ROOT / rel
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


provider_cfg = _load_yaml("configs/provider.yaml")
task_cfg     = _load_yaml("configs/tasks/medium.yaml")
codebase_cfg = _load_yaml("configs/codebase.yaml")
tools_cfg    = _load_yaml("configs/tools.yaml")
weights_cfg  = _load_yaml("configs/benchmark_weights.yaml")


# ── Helper Functions ─────────────────────────────────────────────────────────

def _show_judge_log(run_path: Path):
    log_path = run_path / "judge_log.json"
    if not log_path.exists():
        st.caption(_t("no_reasoning"))
        return
    
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
        
        total_cost = sum(item.get("cost_usd", 0) for item in log if "cost_usd" in item)
        st.write(f"**{_t('judge_calls_header')}:** ${total_cost:.5f}")
        
        for item in log:
            crit = item.get("criterion", "unknown")
            score = item.get("score", 0.0)
            reasoning = item.get("reasoning", "")
            
            with st.expander(f"{crit} (Score: {score})"):
                st.write(f"**Reasoning:** {reasoning}")
                if "input_tokens" in item:
                    st.write(f"**Tokens:** {item.get('input_tokens')} in / {item.get('output_tokens')} out")
                if "cost_usd" in item:
                    st.write(f"**Cost:** ${item.get('cost_usd', 0):.6f}")
                if "error" in item:
                    st.error(f"Error: {item['error']}")
    except Exception as e:
        st.error(f"Failed to load judge log: {e}")


# ── Data ──────────────────────────────────────────────────────────────────────

@st.cache_data
def load_data() -> pd.DataFrame:
    rows = []
    for f in _glob.glob(str(_ROOT / "results" / "run_*" / "metrics.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            folder_name = os.path.basename(os.path.dirname(f))
            parts = folder_name.split("_")
            # run_{ts_date}_{ts_time}_{rest}
            d["timestamp"] = f"{parts[1]}_{parts[2]}" if len(parts) >= 3 else "unknown"
            
            # Identify repetition if present
            rep_idx = -1
            for i, p in enumerate(parts):
                if p.startswith("r") and len(p) == 4 and p[1:].isdigit():
                    rep_idx = i
                    break
            
            if rep_idx != -1:
                d["config_id_full"] = "_".join(parts[rep_idx+1:])
                d["repetition"] = parts[rep_idx]
            else:
                d["config_id_full"] = "_".join(parts[3:])
                d["repetition"] = "r001"

            patch = _ROOT / "results" / folder_name / "final.patch"
            d["final_patch"] = patch.read_text(encoding="utf-8") if patch.exists() else ""
            msgs = _ROOT / "results" / folder_name / "agent_messages.json"
            d["agent_messages"] = json.loads(msgs.read_text(encoding="utf-8")) if msgs.exists() else []
            rows.append(d)
        except Exception:
            pass
    return pd.DataFrame(rows)


df = load_data()

_F0 = ["time_to_target", "context_waste_ratio", "avg_tokens_per_tool", "warmup_sec",
       "retrieval_precision", "retrieval_recall", "eval_score", "cost_usd",
       "duration_sec", "success_per_token", "task_solved_score", "correctness_score",
       "tool_correctness_score", "context_quality_score", "minimality_score",
       "pattern_adherence_score", "tool_sequence_score"]
_I0 = ["agent_cycles", "errors", "tool_errors", "model_calls", "tool_calls",
       "patch_lines", "total_tokens", "input_tokens", "output_tokens", "tool_tokens"]
_B0 = ["success", "made_changes"]
_S0 = ["execution_result", "model_name", "judge_model",
       "judge_reasoning_task", "judge_reasoning_tools", "judge_reasoning_context",
       "judge_reasoning_correctness", "judge_reasoning_minimality",
       "judge_reasoning_pattern", "judge_reasoning_tool_sequence"]

for c in _F0:
    if c not in df.columns: df[c] = 0.0
for c in _I0:
    if c not in df.columns: df[c] = 0
for c in _B0:
    if c not in df.columns: df[c] = False
for c in _S0:
    if c not in df.columns: df[c] = ""
if "agent_messages" in df.columns:
    df["agent_messages"] = df["agent_messages"].apply(lambda x: x if isinstance(x, list) else [])
if "final_patch" in df.columns:
    df["final_patch"] = df["final_patch"].apply(lambda x: x if isinstance(x, str) else "")

_arch = {c["id"]: c.get("archetype", "unknown") for c in tools_cfg.get("configs", [])}
df["archetype"] = df["config_id_full"].map(_arch).fillna("unknown")


# ── Page config (must be first Streamlit call) ────────────────────────────────

st.set_page_config(layout="wide", page_title="Benchmark Dashboard")

# Language must be initialised before _t() is first used
if "lang" not in st.session_state:
    st.session_state["lang"] = "en"


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title(_t("sidebar_title"))

lang_choice = st.sidebar.selectbox(
    _t("language"),
    options=["en", "ru"],
    format_func=lambda x: "🇬🇧 English" if x == "en" else "🇷🇺 Русский",
    key="lang",
)

st.sidebar.markdown("---")
st.title(_t("app_title"))

if df.empty:
    st.warning(_t("no_data_run"))
    st.stop()

# Session detection
all_sessions = list_sessions(str(_ROOT / "results"))
session_options = []
session_map = {}

for s in all_sessions:
    label = s["session_id"]
    if not s.get("is_pseudo") and s.get("n_runs", 1) > 1:
        label = f"📊 {s['session_id']} ({s['n_runs']} runs)"
    session_options.append(label)
    session_map[label] = s

selected_label = st.sidebar.selectbox(_t("run_timestamp"), session_options)
selected_session = session_map[selected_label]
selected_ts = selected_session["session_id"]

# Task Info in Sidebar
task_name = selected_session.get("task_name", selected_session.get("task", "—"))
task_diff = selected_session.get("task_difficulty", "—")
codebase = selected_session.get("codebase_name", selected_session.get("codebase", "—"))

diff_icons = {"hard": "🔴", "medium": "🟡", "easy": "🟢"}
icon = diff_icons.get(task_diff.lower(), "⚪")

st.sidebar.markdown(f"**Task:** {task_name} ({icon} {task_diff})")
st.sidebar.markdown(f"**Repo:** {codebase}")
st.sidebar.caption(f"📁 {_ROOT / 'results'}")

is_multi_run = not selected_session.get("is_pseudo") and selected_session.get("n_runs", 1) > 1

filter_mode = st.sidebar.radio(_t("status_label"),
                               [_t("status_all"), _t("status_pass"), _t("status_fail")])

# Data aggregation
fdf_raw = df[df["timestamp"] == selected_ts].copy()

if is_multi_run:
    n_expected = selected_session.get("n_runs_expected", selected_session.get("n_runs", 0) * selected_session.get("n_configs", 0))
    n_completed = selected_session.get("n_runs_completed", 0)
    reps_expected = selected_session.get("n_reps_expected", selected_session.get("n_runs", 0))
    reps_completed = selected_session.get("n_reps_completed", 0)
    coverage = selected_session.get("coverage_pct", (n_completed / n_expected * 100) if n_expected > 0 else 0)
    
    color = "green" if coverage >= 80 else "orange" if coverage >= 50 else "red"
    
    st.sidebar.markdown(f"""
    <div style='color: {color};'>
    📊 {n_completed}/{n_expected} ранов завершено<br/>
    {reps_completed}/{reps_expected} Rep полных · coverage {coverage:.0f}%<br/>
    p75 агрегация
    </div>
    """, unsafe_allow_code=True)
    
    # Aggregate data
    agg = aggregate_session(str(_ROOT / "results"), selected_ts, percentile=75)
    rows = []
    for config_id, stats in agg.items():
        row = {k: v for k, v in stats.items() if k != "metadata"}
        row["config_id_full"] = config_id
        row["timestamp"] = selected_ts
        row["n_runs_total"] = selected_session.get("n_runs", 1)
        row["n_runs_completed"] = stats["metadata"].get("n", 0)
        
        # Recover non-numeric fields from fdf_raw
        orig_matches = fdf_raw[fdf_raw["config_id_full"] == config_id]
        if not orig_matches.empty:
            for col in ["archetype", "model_name", "judge_model"]:
                if col in orig_matches.columns:
                    row[col] = orig_matches.iloc[0][col]
            # Take agent_messages and final_patch from the first repetition if available
            row["agent_messages"] = orig_matches.iloc[0]["agent_messages"]
            row["final_patch"] = orig_matches.iloc[0]["final_patch"]
        
        rows.append(row)
    fdf = pd.DataFrame(rows)
else:
    fdf = fdf_raw

if filter_mode == _t("status_pass"): fdf = fdf[fdf["success"] == True]
if filter_mode == _t("status_fail"): fdf = fdf[fdf["success"] == False]

st.sidebar.markdown("---")
st.sidebar.metric(_t("configs_in_view"), len(fdf))
st.sidebar.metric(_t("pass_rate"), f"{fdf['success'].mean()*100:.0f}%" if len(fdf) else "—")


# ── Tabs ──────────────────────────────────────────────────────────────────────

(tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8) = st.tabs([
    _t("tab_leaderboard"), _t("tab_explorer"), _t("tab_charts"),
    _t("tab_run_info"), _t("tab_weights"), _t("tab_glossary"),
    _t("tab_deep_dive"), _t("tab_all_metrics"),
])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 1 — Leaderboard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab1:
    header_suffix = f"{task_name} ({task_diff})" if task_name != "—" else selected_ts
    st.header(f"{_t('leaderboard_header')} — {header_suffix} — {selected_ts}")
    
    if not is_multi_run:
        st.warning("⚠️ **SINGLE RUN SESSION** — Results lack statistical significance. Run with `--runs 5` or more to enable tie-bands and reliability checks.")
    
    if fdf.empty:
        st.info(_t("no_data"))
    else:
        # Partition and Rank
        ranked_raw, not_ranked = partition_by_status(fdf.to_dict('records'))
        ranked = rank_with_tiebands(ranked_raw, "net_spt", "_spt_ci_lo", "_spt_ci_hi")

        rdf = pd.DataFrame(ranked)
        nrdf = pd.DataFrame(not_ranked)

        # Ensure display name column exists
        for df_ in [rdf, nrdf]:
            if not df_.empty and "config_name" not in df_.columns:
                df_["config_name"] = df_.get("config_id_full", pd.Series([""] * len(df_)))

        if not rdf.empty:
            st.subheader(_t("ranked_results"))

            # Display net_spt with CI
            if is_multi_run:
                rdf["Net SPT [90% CI]"] = rdf.apply(
                    lambda r: f"{r.get('net_spt', 0.0):.1f} [{r.get('_spt_ci_lo', 0.0):.1f}, {r.get('_spt_ci_hi', 0.0):.1f}]",
                    axis=1
                )
            else:
                rdf["Net SPT"] = rdf["net_spt"].apply(lambda x: f"{x:.1f}")

            cols_to_show = ["rank", "tie_band", "config_name"]
            if is_multi_run:
                cols_to_show.append("Net SPT [90% CI]")
            else:
                cols_to_show.append("Net SPT")

            optional_cols = ["eval_score", "total_tokens", "cost_usd", "_validity_status"]
            if "n_runs_completed" in rdf.columns:
                optional_cols.append("n_runs_completed")
            cols_to_show.extend(optional_cols)
            
            # Localize columns (Block 4.2)
            lang = st.session_state.get("lang", "en")
            display_df = rdf[cols_to_show].rename(columns=_column_names.get(lang, {}))
            
            # Localize status values
            status_col = _column_names[lang].get("_validity_status", "_validity_status")
            if status_col in display_df.columns:
                display_df[status_col] = display_df[status_col].map(lambda x: _STATUS_MAP[lang].get(x, x))

            st.dataframe(display_df, use_container_width=True, hide_index=True)

            if (rdf["net_spt"] == 0).all():
                st.warning(_t("spt_zero_warning"))
            
            # CSV Export
            csv = rdf.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=_t("download_csv"),
                data=csv,
                file_name=f"benchmark_{selected_ts}_aggregated.csv",
                mime='text/csv',
            )

        if not nrdf.empty:
            st.subheader(_t("not_ranked_results"))
            nr_cols = ["config_name"]
            if "_validity_status" in nrdf.columns:
                nr_cols.append("_validity_status")
            if "n_runs_completed" in nrdf.columns:
                nr_cols.append("n_runs_completed")
            
            lang = st.session_state.get("lang", "en")
            nr_display_df = nrdf[nr_cols].rename(columns=_column_names.get(lang, {}))
            
            # Localize status values
            status_col = _column_names[lang].get("_validity_status", "_validity_status")
            if status_col in nr_display_df.columns:
                nr_display_df[status_col] = nr_display_df[status_col].map(lambda x: _STATUS_MAP[lang].get(x, x))

            st.dataframe(nr_display_df, use_container_width=True, hide_index=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 2 — Config Explorer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab2:
    st.header(_t("explorer_header"))
    if is_multi_run:
        st.caption(f"Showing p75 across {selected_session.get('n_runs')} runs (session {selected_ts}) — {len(fdf)} configs")
    else:
        st.caption(_t("explorer_caption", ts=selected_ts, n=len(fdf)))
    c1, c2 = st.columns(2)
    sort_by  = c1.selectbox(_t("sort_by"), ["eval_score","total_tokens","cost_usd","duration_sec","success"], key="ex_s")
    sort_asc = c2.checkbox(_t("ascending"), False, key="ex_a")
    sdf = fdf.sort_values(sort_by, ascending=sort_asc)

    _JUDGE_F = [
        ("Task", "task_solved_score"), ("Correct", "correctness_score"),
        ("Tools", "tool_correctness_score"), ("Context", "context_quality_score"),
        ("Minimal", "minimality_score"), ("Pattern", "pattern_adherence_score"),
        ("Seq", "tool_sequence_score"),
    ]
    _REASON_F = {
        "Task Solved": "judge_reasoning_task", "Tool Use": "judge_reasoning_tools",
        "Context": "judge_reasoning_context", "Correctness": "judge_reasoning_correctness",
        "Minimality": "judge_reasoning_minimality", "Pattern": "judge_reasoning_pattern",
        "Tool Sequence": "judge_reasoning_tool_sequence",
    }

    for _, row in sdf.iterrows():
        ok   = row.get("success", False)
        icon = "✅" if ok else "❌"
        hdr  = (f"{icon} **{row['config_id_full']}** — "
                f"eval={float(row.get('eval_score',0)):.2f} | "
                f"tokens={int(float(row.get('total_tokens',0))):,} | "
                f"${float(row.get('cost_usd',0)):.4f}")
        with st.expander(hdr, expanded=False):
            cols = st.columns(4)
            cols[0].metric(_t("metric_eval"),      f"{float(row.get('eval_score',0)):.3f}")
            cols[1].metric(_t("metric_tokens"),    f"{int(float(row.get('total_tokens',0))):,}")
            cols[2].metric(_t("metric_cost"),      f"${float(row.get('cost_usd',0)):.4f}")
            cols[3].metric(_t("metric_duration"),  f"{float(row.get('duration_sec',0)):.1f}s")
            cols2 = st.columns(4)
            cols2[0].metric(_t("metric_cycles"),      int(float(row.get("agent_cycles", 0))))
            cols2[1].metric(_t("metric_tool_calls"),  int(float(row.get("tool_calls", 0))))
            cols2[2].metric(_t("metric_ttt"),         int(float(row.get("time_to_target", 0))))
            cols2[3].metric(_t("metric_waste"),       f"{float(row.get('context_waste_ratio',0))*100:.1f}%")
            st.markdown(f"**{_t('judge_scores')}**")
            jc = st.columns(7)
            for i, (lbl, fld) in enumerate(_JUDGE_F):
                jc[i].metric(lbl, f"{row.get(fld,0):.2f}")
            reasons = [(l, row.get(f,"")) for l, f in _REASON_F.items()
                       if row.get(f) and str(row.get(f)) not in ("","nan")]
            if reasons:
                st.markdown(f"**{_t('judge_reasoning')}**")
                rc = st.columns(2)
                for i, (l, txt) in enumerate(reasons):
                    with rc[i % 2]: st.markdown(f"*{l}:* {txt}")
            else:
                st.caption(_t("no_reasoning"))

            # Judge Calls (Block 2.2)
            st.markdown("---")
            st.markdown(f"**{_t('judge_calls')}**")
            run_id_clean = row['config_id_full']
            run_folder = f"run_{selected_ts}_{run_id_clean}"
            if is_multi_run:
                run_folder = f"run_{selected_ts}_r001_{run_id_clean}"
            
            _show_judge_log(_ROOT / "results" / run_folder)

            patch = row.get("final_patch", "")
            if patch and patch not in ("Patch file not found.", "No patch available."):
                st.markdown(f"**{_t('code_diff')}**")
                st.code(patch, language="diff")
            msgs = row.get("agent_messages", [])
            if isinstance(msgs, list) and msgs:
                st.markdown(f"**{_t('agent_timeline')}**")
                tl, cyc = [], 0
                for m in msgs:
                    if m.get("role") == "tool": cyc += 1
                    for tc in (m.get("tool_calls") or []):
                        if not isinstance(tc, dict): continue
                        name = tc.get("function",{}).get("name","?") if "function" in tc else tc.get("tool_name","?")
                        args = str(tc.get("function",{}).get("arguments",""))[:100] if "function" in tc else str(tc.get("input",""))[:100]
                        tl.append({"Cycle": cyc, "Tool": name, "Args": args})
                st.dataframe(tl or [{"info": _t("no_tool_calls")}], use_container_width=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 3 — Charts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab3:
    all_cfgs = sorted(fdf["config_id_full"].unique())
    METRICS_LIST = [
        "eval_score","task_solved_score","correctness_score","tool_correctness_score",
        "context_quality_score","minimality_score","pattern_adherence_score","tool_sequence_score",
        "retrieval_precision","retrieval_recall","total_tokens","cost_usd","duration_sec",
        "success_per_token","tool_calls","agent_cycles","avg_tokens_per_tool",
        "time_to_target","context_waste_ratio","warmup_sec",
    ]
    st.subheader(_t("bar_chart_header"))
    bc1, bc2 = st.columns([1, 3])
    with bc1:
        met      = st.selectbox(_t("y_axis_metric"), METRICS_LIST, key="bar_met")
        sel_cfgs = st.multiselect(_t("configs_to_show"), all_cfgs, default=all_cfgs, key="bar_cfgs")
        color_by = st.selectbox(_t("color_by"), ["archetype","success","none"], key="bar_col")
    with bc2:
        bdf = fdf[fdf["config_id_full"].isin(sel_cfgs)].copy()
        if bdf.empty:
            st.info(_t("no_data"))
        else:
            if color_by == "archetype":
                fig_b = px.bar(bdf, x="config_id_full", y=met, color="archetype", barmode="group")
            elif color_by == "success":
                bdf["Pass"] = bdf["success"].map({True:"PASS",False:"FAIL"})
                fig_b = px.bar(bdf, x="config_id_full", y=met, color="Pass",
                               color_discrete_map={"PASS":"#10b981","FAIL":"#ef4444"})
            else:
                fig_b = px.bar(bdf, x="config_id_full", y=met)
            fig_b.update_layout(xaxis_tickangle=-45, title=f"{met}")
            st.plotly_chart(fig_b, use_container_width=True)

    st.divider()
    ALL_DIMS = [
        "task_solved_score","correctness_score","tool_correctness_score",
        "context_quality_score","minimality_score","pattern_adherence_score",
        "tool_sequence_score","retrieval_precision","retrieval_recall","eval_score",
    ]
    st.subheader(_t("radar_header"))
    rc1, rc2 = st.columns([1, 3])
    with rc1:
        r_cfgs = st.multiselect(_t("configs_max5"), all_cfgs, default=all_cfgs[:min(3,len(all_cfgs))],
                                 max_selections=5, key="rad_cfgs")
        r_dims = st.multiselect(_t("dims_max12"), ALL_DIMS, default=ALL_DIMS[:7],
                                 max_selections=12, key="rad_dims")
    with rc2:
        if len(r_cfgs) >= 1 and len(r_dims) >= 3:
            fig_r = go.Figure()
            for cid in r_cfgs:
                row = fdf[fdf["config_id_full"] == cid]
                if row.empty: continue
                vals = [float(row.iloc[0].get(d,0)) for d in r_dims]
                fig_r.add_trace(go.Scatterpolar(
                    r=vals+[vals[0]], theta=r_dims+[r_dims[0]],
                    mode="lines+markers", name=cid))
            fig_r.update_layout(polar=dict(radialaxis=dict(visible=True,range=[0,1])),
                                 title=_t("radar_header"))
            st.plotly_chart(fig_r, use_container_width=True)
        else:
            st.info(_t("radar_hint"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 4 — Run Info
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab4:
    st.header(_t("run_info_header"))
    ri1, ri2 = st.columns(2)
    with ri1:
        st.subheader(_t("provider_model"))
        if provider_cfg:
            st.json(provider_cfg)
        else:
            st.warning(f"configs/provider.yaml {_t('not_found')}")
        st.subheader(_t("task_label"))
        if task_cfg:
            st.write(f"**{_t('task_name')}:** {task_cfg.get('name','—')}")
            st.write(f"**{_t('task_difficulty')}:** {task_cfg.get('difficulty','—')}")
            st.text_area(_t("task_description"), task_cfg.get("description",""), height=150, disabled=True)
            st.write(f"**{_t('task_test_cmd')}:** `{task_cfg.get('test_cmd','—')}`")
            st.write(f"**{_t('task_timeout')}:** {task_cfg.get('timeout_sec','—')}s")
            st.markdown(f"**{_t('task_required_files')}:**")
            for rf in task_cfg.get("required_files",[]):
                st.code(rf)
        else:
            st.warning(f"configs/tasks/medium.yaml {_t('not_found')}")
    with ri2:
        st.subheader(_t("codebase_label"))
        if codebase_cfg:
            for k, v in codebase_cfg.items():
                st.write(f"**{k}:** {v}")
        else:
            st.warning(f"configs/codebase.yaml {_t('not_found')}")
        st.subheader(f"{_t('tools_configs')} ({len(tools_cfg.get('configs',[]))})")
        if tools_cfg.get("configs"):
            rows_t = [{"id": c.get("id",""), "name": c.get("name",""),
                       "archetype": c.get("archetype",""),
                       "tools": ", ".join(c.get("tools",[])),
                       "model": c.get("model","—"),
                       "max_steps": c.get("max_steps","—")}
                      for c in tools_cfg["configs"]]
            st.dataframe(pd.DataFrame(rows_t), use_container_width=True)
        else:
            st.warning(f"configs/tools.yaml {_t('not_found')}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 5 — Weights
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab5:
    st.header(_t("weights_header"))
    if not weights_cfg:
        st.warning(f"configs/benchmark_weights.yaml {_t('not_found')}")
    else:
        eval_w = weights_cfg.get("eval_weights", {})
        st.subheader(_t("eval_composite_header"))
        st.caption(_t("eval_composite_caption"))
        if eval_w:
            edf = pd.DataFrame([{_t("col_metric"): k, _t("col_weight"): v} for k, v in eval_w.items()])
            fig_e = px.bar(edf, x=_t("col_metric"), y=_t("col_weight"),
                           title=_t("eval_composite_chart"), color=_t("col_metric"), text_auto=True)
            st.plotly_chart(fig_e, use_container_width=True)
            st.dataframe(edf, use_container_width=True)
        st.divider()
        all_w = weights_cfg.get("all_metrics_weights", {})
        st.subheader(_t("all_metrics_header"))
        st.caption(_t("all_metrics_caption"))
        if all_w:
            rows_w = [{_t("col_metric"): m,
                       _t("col_weight"): s.get("weight",0),
                       _t("col_direction"): s.get("direction","—"),
                       _t("col_description"): s.get("description","")}
                      for m, s in all_w.items() if isinstance(s, dict)]
            adf = pd.DataFrame(rows_w)
            fig_a = px.bar(adf, x=_t("col_metric"), y=_t("col_weight"),
                           color=_t("col_direction"),
                           title=_t("all_metrics_chart"), height=500,
                           color_discrete_map={"higher":"#10b981","lower":"#ef4444"},
                           text_auto=True)
            fig_a.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig_a, use_container_width=True)
            st.dataframe(adf, use_container_width=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 6 — Glossary
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab6:
    st.header(_t("glossary_header"))
    st.caption(_t("glossary_caption"))

    # Terminology Section (Block 7.3)
    st.subheader(_t("terminology_header"))
    with st.expander("Task → Config → Run → Rep (Suite) → Session", expanded=True):
        st.markdown("""
| Term | Definition |
|------|-----------|
| **Task** | A coding problem: description, target_file, test_cmd, difficulty. |
| **Config** | One toolset + agent parameters (e.g. `08_git_grep`). |
| **Run** | Single execution of one Config on one Task. |
| **Rep (Suite)** | One full pass over all Configs (21 Runs). |
| **Session** | Full series of repetitions (N Reps × M Configs). |
| **Budget** | $5.00 per Suite (Rep), $0.40 per Agent Run, $1.00 per Judge Run. |
""")

    # field → (range, direction, where_shown, EN_description)
    GLOSSARY: dict[str, dict[str, tuple]] = {
        "Eval Judge Scores": {
            "task_solved_score": ("0–1","higher","Leaderboard · Explorer · Charts · Weights",
                "Primary signal. Did the agent fully accomplish the user request? Scored by an LLM judge after reviewing the agent's patch, messages, and test results. Contributes 35% of Eval Composite."),
            "correctness_score": ("0–1","higher","Explorer · Charts · Weights",
                "Is the produced code technically correct, bug-free, and free of unintended side effects? Contributes 20%."),
            "tool_correctness_score": ("0–1","higher","Explorer · Charts · Weights",
                "Core benchmark dimension. Did the agent choose the right retrieval tools for the task, with correct arguments? Contributes 10%."),
            "context_quality_score": ("0–1","higher","Explorer · Charts · Weights",
                "Was the gathered context relevant and sufficient? Penalises over-reading and under-reading. Contributes 15%."),
            "minimality_score": ("0–1","higher","Explorer · Charts · Weights",
                "Surgical edits only. Penalises unnecessary file rewrites or large blast radius. Contributes 10%."),
            "pattern_adherence_score": ("0–1","higher","Explorer · Charts · Weights",
                "Does the produced code follow project conventions: naming, style, import order? Contributes 5%."),
            "tool_sequence_score": ("0–1","higher","Explorer · Charts · Weights",
                "Were tool calls in a logical, efficient order? Contributes 5%."),
        },
        "Composite & Summary Scores": {
            "eval_score": ("0–1","higher","Leaderboard · Explorer · Charts",
                "Weighted geometric mean of the 7 LLM-judge dimensions. Returns 0 if any dimension scores 0."),
            "success_per_token (SPT)": (">0, higher","higher","Leaderboard",
                "Efficiency: task_solved_score × 1,000,000 ÷ total_tokens. Rewards agents completing the task with fewer tokens."),
            "success": ("True/False","higher","Leaderboard · Explorer · All Metrics",
                "True if agent made code changes (patch_lines > 0) AND tests did not regress."),
            "made_changes": ("True/False","—","Explorer · All Metrics",
                "True if git diff HEAD is non-empty at end of run."),
        },
        "Retrieval Quality": {
            "retrieval_precision": ("0–1","higher","Charts · Weights · All Metrics",
                "Of all files read, what fraction were in required_files? High = targeted reading."),
            "retrieval_recall": ("0–1","higher","Charts · Weights · All Metrics",
                "Of all required_files, what fraction were actually read? High = no critical file missed."),
            "time_to_target (TTT)": ("0–N cycles","lower","Leaderboard · Charts · Weights · All Metrics",
                "Cycle number when the first required file was first read. 0 = never read. Lower = faster discovery."),
            "context_waste_ratio": ("0–1","lower","Leaderboard · Charts · Weights · All Metrics",
                "(total_read_tokens − useful_read_tokens) / total_read_tokens. Lower = more targeted reading."),
            "avg_tokens_per_tool": ("tokens","lower","Charts · Weights · All Metrics",
                "tool_tokens / tool_calls. Lower = agent reads small targeted files rather than dumping entire codebases."),
        },
        "Token & Cost Efficiency": {
            "total_tokens": ("count","lower","Leaderboard · All Metrics",
                "input_tokens + output_tokens + tool_tokens. All tokens billed by the provider."),
            "input_tokens": ("count","lower","All Metrics",
                "Tokens in context sent to LLM: system prompt + conversation history + tool results."),
            "output_tokens": ("count","lower","All Metrics",
                "Tokens in LLM responses: reasoning + tool call JSON."),
            "tool_tokens": ("count","lower","All Metrics",
                "Tokens in tool-response messages returned to the model."),
            "cost_usd": ("USD","lower","Leaderboard · Charts · Weights · All Metrics",
                "Estimated API cost from token counts and model pricing. Tool tokens priced as input."),
            "duration_sec": ("seconds","lower","Charts · Weights · All Metrics",
                "Wall-clock time from first model call to last tool call. Excludes MCP warmup (warmup_sec)."),
            "warmup_sec": ("seconds","lower","All Metrics",
                "Time warming up MCP servers before the main timer starts. Not charged to duration_sec."),
        },
        "Agent Behaviour": {
            "model_calls": ("count","lower","Charts · Weights · All Metrics",
                "Number of LLM API calls = number of assistant role messages. Each call sends full context."),
            "tool_calls": ("count","lower","Explorer · All Metrics",
                "Total tool invocations. Parallel calls in one response count separately."),
            "agent_cycles": ("count","lower","Leaderboard · Explorer · All Metrics",
                "Think→tool→response cycles = number of tool role messages. Diff from tool_calls = parallel calls."),
            "patch_lines": ("count","—","Explorer · All Metrics",
                "Lines added + removed in the final git diff. Rough measure of edit scope."),
        },
        "Reliability": {
            "errors": ("count","lower","Charts · Weights · All Metrics",
                "Test failures at end of run. Non-zero = agent introduced a regression."),
            "tool_errors": ("count","lower","Charts · Weights · All Metrics",
                "Tool calls returning an error string: wrong args, file not found, timeout."),
            "execution_result": ("string","—","Explorer · All Metrics",
                "'passed', 'failed', 'baseline_maintained', or 'not_verified'. Summarises test run outcome."),
        },
        "Run Metadata": {
            "model_name": ("string","—","All Metrics",
                "Model identifier, e.g. 'openai/gpt-4.1-mini'. From provider.yaml; overrideable per config."),
            "judge_model": ("string","—","All Metrics",
                "Model used as LLM judge. Usually more powerful than the agent model."),
            "timestamp": ("YYYYMMDD_HHMMSS","—","Leaderboard · Sidebar",
                "When the benchmark run started. Groups configs from the same suite run."),
        },
    }

    search = st.text_input(f"🔍 {_t('search_placeholder')}", key="gloss_q")
    total = 0
    for section, items in GLOSSARY.items():
        matching = {k: v for k, v in items.items()
                    if not search
                    or search.lower() in k.lower()
                    or search.lower() in v[3].lower()
                    or search.lower() in v[2].lower()}
        if not matching: continue
        with st.expander(f"**{section}** ({len(matching)})", expanded=(not search or len(matching) <= 4)):
            for metric, (rng, direction, where, desc) in matching.items():
                cm, cr = st.columns([2, 5])
                with cm:
                    badge = "▲ higher" if direction == "higher" else ("▼ lower" if direction == "lower" else "— info")
                    st.markdown(f"**`{metric}`**")
                    st.caption(f"{rng} · {badge}")
                with cr:
                    st.markdown(desc)
                    st.caption(f"*{_t('glossary_shown_in')}: {where}*")
                st.divider()
                total += 1
    if search and total == 0:
        st.info(_t("glossary_no_results", q=search))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 7 — Config Deep Dive
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab7:
    st.header(_t("deep_dive_header"))
    if fdf.empty:
        st.info(_t("no_data"))
    else:
        sel = st.selectbox(_t("select_config"), fdf["config_id_full"].tolist(), key="dd_cfg")
        row = fdf[fdf["config_id_full"] == sel].iloc[0]
        dims = {f: float(row.get(f,0)) for f in [
            "task_solved_score","correctness_score","tool_correctness_score",
            "context_quality_score","minimality_score","pattern_adherence_score","tool_sequence_score"]}
        meds = {k: float(fdf[k].median()) if k in fdf.columns else 0.0 for k in dims}
        rdf = pd.DataFrame([dims, meds], index=["Selected","Median"]).T.reset_index()
        rdf.columns = ["Dimension","Selected","Median"]
        fig_dd = px.line_polar(rdf, r="Selected", theta="Dimension",
                               line_close=True, title=_t("judge_dims_vs_median"))
        fig_dd.add_trace(go.Scatterpolar(r=rdf["Median"], theta=rdf["Dimension"], mode="lines", name="Median"))
        st.plotly_chart(fig_dd, use_container_width=True)
        with st.expander(_t("judge_reasoning")):
            reasons = [(l, row.get(f,"")) for l, f in {
                "Task Solved":"judge_reasoning_task","Tool Use":"judge_reasoning_tools",
                "Context":"judge_reasoning_context","Correctness":"judge_reasoning_correctness",
                "Minimality":"judge_reasoning_minimality","Pattern":"judge_reasoning_pattern",
                "Tool Sequence":"judge_reasoning_tool_sequence"}.items()
                if row.get(f) and str(row.get(f)) not in ("","nan")]
            if reasons:
                rc = st.columns(2)
                for i, (l, txt) in enumerate(reasons):
                    with rc[i%2]: st.markdown(f"*{l}:* {txt}")
            else:
                st.info(_t("no_reasoning_deep"))
        
        # Judge Calls (Block 2.2)
        with st.expander(_t("judge_calls")):
            run_id_clean = row['config_id_full']
            run_folder = f"run_{selected_ts}_{run_id_clean}"
            if is_multi_run:
                run_folder = f"run_{selected_ts}_r001_{run_id_clean}"
            _show_judge_log(_ROOT / "results" / run_folder)

        with st.expander(_t("code_diff")):
            p = row.get("final_patch","")
            st.code(p if p else _t("no_patch_deep"), language="diff")
        with st.expander(_t("agent_timeline")):
            msgs = row.get("agent_messages",[])
            if not isinstance(msgs, list): msgs = []
            tl, cyc = [], 0
            for m in msgs:
                if m.get("role") == "tool": cyc += 1
                for tc in (m.get("tool_calls") or []):
                    if not isinstance(tc, dict): continue
                    name = tc.get("function",{}).get("name","?") if "function" in tc else tc.get("tool_name","?")
                    args = str(tc.get("function",{}).get("arguments",""))[:120] if "function" in tc else str(tc.get("input",""))[:120]
                    tl.append({"Cycle":cyc,"Tool":name,"Args":args})
            st.dataframe(tl or [{"info": _t("no_tool_calls")}], use_container_width=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 8 — All Metrics
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab8:
    st.header(_t("all_metrics_tab_header"))
    st.caption(_t("all_metrics_tab_caption"))
    if fdf.empty:
        st.info(_t("no_data"))
    else:
        ALL_COLS = [
            "config_id_full","archetype","model_name",
            "success","success_rate","n_runs_completed","made_changes","execution_result",
            "eval_score","task_solved_score","correctness_score","tool_correctness_score",
            "context_quality_score","minimality_score","pattern_adherence_score","tool_sequence_score",
            "success_per_token","retrieval_precision","retrieval_recall",
            "time_to_target","context_waste_ratio",
            "total_tokens","input_tokens","output_tokens","tool_tokens","avg_tokens_per_tool",
            "cost_usd","duration_sec","warmup_sec",
            "model_calls","tool_calls","agent_cycles",
            "files_read","files_changed","patch_lines",
            "errors","tool_errors","cost_exceeded","token_exceeded","judge_model",
        ]
        exist = [c for c in ALL_COLS if c in fdf.columns]
        am = fdf[exist].copy()
        for c in am.select_dtypes(include=["float64","float32"]).columns:
            if c in ("retrieval_precision","retrieval_recall") or c.endswith("_ratio"):
                am[c] = am[c].map(lambda x: f"{x:.3f}")
            elif c == "cost_usd":
                am[c] = am[c].map(lambda x: f"${x:.5f}")
            elif c == "duration_sec":
                am[c] = am[c].map(lambda x: f"{x:.1f}s")
            elif "score" in c or c in ("eval_score","success_per_token"):
                am[c] = am[c].map(lambda x: f"{x:.3f}")

        s1, s2 = st.columns(2)
        am_sort = s1.selectbox(_t("sort_by"), exist,
                               index=exist.index("eval_score") if "eval_score" in exist else 0,
                               key="am_sort")
        am_asc  = s2.checkbox(_t("ascending"), False, key="am_asc")
        am = am.sort_values(am_sort, ascending=am_asc)
        st.dataframe(am, use_container_width=True, height=600)

        st.divider()
        st.subheader(_t("stat_summary"))
        num_cols = [c for c in exist if fdf[c].dtype in ("float64","float32","int64","int32","bool")]
        if num_cols:
            st.dataframe(fdf[num_cols].describe().T.round(3), use_container_width=True)
