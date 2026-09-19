from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    provider: str = os.getenv("MODEL_PROVIDER", "mock")
    api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    investigator_model: str = os.getenv("INVESTIGATOR_MODEL", "google/gemini-3-flash-preview")
    decision_model: str = os.getenv("DECISION_MODEL", "~typesafe/jev-latest")
    jev_enabled: bool = os.getenv("JEV_ENABLED", "false").lower() == "true"
    database_path: str = os.getenv("DATABASE_PATH", "./lab.sqlite3")
    max_model_calls: int = int(os.getenv("MAX_MODEL_CALLS", "90"))
    max_tools_per_agent: int = int(os.getenv("MAX_TOOL_CALLS_PER_AGENT", "24"))
    max_total_agents: int = int(os.getenv("MAX_TOTAL_AGENTS", "9"))
    max_workers_per_lead: int = int(os.getenv("MAX_WORKERS_PER_LEAD", "2"))
    max_depth: int = int(os.getenv("MAX_DELEGATION_DEPTH", "2"))
    max_cost_usd: float = float(os.getenv("MAX_COST_USD", "5"))

    def validate(self) -> None:
        if self.provider not in {"mock", "openrouter"}:
            raise ValueError("MODEL_PROVIDER must be mock or openrouter")
        if self.provider == "openrouter" and not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is required for openrouter")
        if not (1 <= self.max_total_agents <= 30 and 1 <= self.max_workers_per_lead <= 5):
            raise ValueError("Invalid agent limits")
        if self.max_model_calls < 3 or self.max_tools_per_agent < 3 or self.max_cost_usd <= 0:
            raise ValueError("Invalid resource budgets")
