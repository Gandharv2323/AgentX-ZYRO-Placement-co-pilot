"""Live smoke test against the real OpenRouter key. Costs nothing: free models only."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, providers  # noqa: E402

print("env applied:", config.load_env() or "(already loaded)")
print("llm_mode:", providers.llm_mode())
if providers.llm_mode() != "openrouter":
    raise SystemExit("no openrouter key configured")

tools = [
    {"name": "search_jobs", "detail": "Search job listings",
     "properties": {"roles": {"type": "array"}, "locations": {"type": "array"},
                    "recency_days": {"type": "integer"}}},
    {"name": "rank_jobs", "detail": "Rank scored jobs", "properties": {"limit": {"type": "integer"}}},
]
history = [{"role": "user", "content":
            "Goal: find 3 AI internships in Pune. Available tools: search_jobs, rank_jobs. "
            'Reply with ONLY this JSON: {"tool":"search_jobs","args":{"roles":["ai"],"locations":["Pune"]}}'}]

plan = providers.plan_step(history, tools)
print("plan:", json.dumps(plan))
assert "tool" in plan or plan.get("done"), plan
print("model chosen:", providers.model_chain()[0])
print("OK")
