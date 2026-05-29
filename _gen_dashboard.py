import sys, os, time
sys.path.insert(0, ".")
from src.features.dashboard_builder import (
    load_latest_per_config, compute_composite, compute_full_composite,
    _normalize_configs, load_weights_config, generate_dashboard
)

eval_w, all_w = load_weights_config()
data = load_latest_per_config("results")
configs = list(data.values())

for cfg in configs:
    cfg["total_tokens"] = cfg.get("total_tokens") or (
        cfg.get("input_tokens", 0) + cfg.get("output_tokens", 0) + cfg.get("tool_tokens", 0)
    )
    cfg.setdefault("success_per_token",
        1_000_000 / cfg["total_tokens"] if cfg.get("success") and cfg["total_tokens"] > 0 else 0.0
    )
    cfg["composite_score"] = compute_composite(cfg, eval_w)

norms = _normalize_configs(configs, all_w)
for cfg, norm in zip(configs, norms):
    cfg["full_composite"] = compute_full_composite(norm, all_w)

print("ID  Name                    OK    EvalComp  FullComp   Tokens")
print("-" * 72)
for cfg in sorted(configs, key=lambda x: x.get("composite_score", 0), reverse=True):
    ok = "PASS" if cfg.get("success") else "FAIL"
    print(f"{cfg['config_id']}  {cfg['config_name']:<22} {ok}  "
          f"{cfg['composite_score']:.3f}     {cfg['full_composite']:.3f}     {cfg['total_tokens']:>7}")

ts = time.strftime("%Y%m%d_%H%M%S")
out = os.path.join("results", f"dashboard_{ts}.html")
generate_dashboard("results", out)
print(f"\nDashboard: {out}")
