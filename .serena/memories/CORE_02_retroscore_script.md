# Retroactive Judge Scoring Script (2026-06-02)

## Purpose
Re-scores saved benchmark runs with the fixed LLM judge.

## Location
`scripts/retroscore_judge.py`

## Usage
```bash
cd /mnt/c/Users/User/a_projects/tools_token_economy
source ~/.venvs/tools_token_economy/bin/activate
PYTHONPATH=/mnt/c/Users/User/a_projects/tools_token_economy python scripts/retroscore_judge.py \
  --session 20260601_131317 \
  --task-name aging_stale
```

## Key Design Choices
- Creates fresh LLMJudge instance per run (prevents budget limit from killing subsequent runs)
- Uses load_dotenv() to load OPENAI_API_KEY from .env
- Patches metrics.json with 7 judge score fields + reasoning
- Handles missing agent_messages.json gracefully (uses empty list)

## After Running
126/126 runs updated, 0 errors. Cost: ~$0.003/run × 126 = ~$0.38 total.
Results written back to each results/run_*/metrics.json.
