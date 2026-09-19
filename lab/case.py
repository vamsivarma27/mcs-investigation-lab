from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class CaseEngine:
    """Public/discoverable case only; this object never opens the vault."""

    def __init__(self, path: Path = DATA / "case_public.json"):
        self.data = json.loads(path.read_text())
        self.evidence = {item["id"]: item for item in self.data["evidence"]}
        self.suspects = {item["id"]: item for item in self.data["suspects"]}
        self.version_hash = hashlib.sha256(canonical(self.data).encode()).hexdigest()
        self.validate()

    def validate(self) -> None:
        d = self.data
        if len(self.suspects) != 8 or len(self.evidence) != len(d["evidence"]):
            raise ValueError("Case must have eight unique suspects and unique evidence IDs")
        if not set(d["initial_evidence"]) <= self.evidence.keys():
            raise ValueError("Unknown initial evidence")
        for item in self.evidence.values():
            if item["reliability"] not in {"verified", "partial", "witness_claim", "untrusted_document"}:
                raise ValueError("Invalid evidence reliability")
            if "suspect_id" in item and item["suspect_id"] not in self.suspects:
                raise ValueError("Unknown evidence suspect")
        for source, targets in d["forensic_map"].items():
            if source not in self.evidence or not set(targets) <= self.evidence.keys():
                raise ValueError("Invalid forensic reference")
        forbidden = {"killer_id", "true_timeline", "canonical_solution", "answer_key", "ground_truth"}
        if forbidden & set(d):
            raise ValueError("Evaluator-only field in public case")
        # The public artifact contains no hidden answer fields or evaluator metadata.
        if any(forbidden & set(item) for item in d["evidence"]):
            raise ValueError("Evaluator-only field in public evidence")

    def overview(self) -> dict:
        return {key: self.data[key] for key in ("id", "title", "version", "premise", "scene", "suspects")}

    def get(self, evidence_id: str) -> dict:
        return self.evidence[evidence_id]

    def search(self, query: str, limit: int = 8) -> list[dict]:
        terms = [term.lower() for term in query.split() if len(term) > 2]
        if not terms:
            return []
        scored = []
        for item in self.evidence.values():
            hay = " ".join([item["title"], item["text"], *item["tags"]]).lower()
            score = sum(term in hay for term in terms)
            if score:
                scored.append((score, item["id"], item))
        return [item for _, _, item in sorted(scored, key=lambda row: (-row[0], row[1]))[:limit]]

    def timeline(self) -> list[dict]:
        return [e for e in self.evidence.values() if "timeline" in e["tags"]]

    def interview(self, suspect_id: str) -> list[dict]:
        return [e for e in self.evidence.values() if e.get("suspect_id") == suspect_id]
