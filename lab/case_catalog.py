from __future__ import annotations

import json
from pathlib import Path

from .case import DATA, CaseEngine


class CaseCatalog:
    """Public case discovery plus trusted vault path resolution."""

    def __init__(self, data_dir: Path = DATA):
        self.data_dir = data_dir
        self._public: dict[str, Path] = {}
        self._cache: dict[str, CaseEngine] = {}
        default = data_dir / "case_public.json"
        if default.exists():
            self._public[json.loads(default.read_text())["id"]] = default
        for path in sorted((data_dir / "cases").glob("*.json")):
            case_id = json.loads(path.read_text())["id"]
            if case_id in self._public:
                raise ValueError(f"Duplicate case ID: {case_id}")
            self._public[case_id] = path

    def get(self, case_id: str) -> CaseEngine:
        if case_id in self._cache:
            return self._cache[case_id]
        path = self._public.get(case_id)
        if not path:
            raise KeyError(case_id)
        self._cache[case_id] = CaseEngine(path)
        return self._cache[case_id]

    def default(self) -> CaseEngine:
        return self.get("meridian-archive")

    def vault_path(self, case_id: str) -> Path:
        if case_id == "meridian-archive":
            return self.data_dir / "case_vault.json"
        path = self.data_dir / "vaults" / f"{case_id}.json"
        if case_id not in self._public or not path.exists():
            raise KeyError(case_id)
        return path

    def list(self) -> list[dict]:
        output = []
        for case_id in self._public:
            data = self.get(case_id).data
            output.append({
                "id": case_id, "title": data["title"], "version": data["version"],
                "premise": data["premise"], "difficulty": data.get("difficulty", "Moderate"),
                "difficulty_rank": data.get("difficulty_rank", 3),
                "difficulty_description": data.get("difficulty_description", "Balanced evidence and red herrings."),
                "category": data.get("category", "Original"),
                "estimated_minutes": data.get("estimated_minutes", 20),
                "suspect_count": len(data["suspects"]), "evidence_count": len(data["evidence"]),
            })
        return sorted(output, key=lambda item: (item["difficulty_rank"], item["title"]))
