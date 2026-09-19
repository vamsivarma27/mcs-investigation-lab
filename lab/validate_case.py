"""Trusted offline case lint; never called by investigator runtime."""
from __future__ import annotations

import json

from .case import DATA, CaseEngine, canonical


def validate() -> dict:
    case = CaseEngine()
    vault = json.loads((DATA / "case_vault.json").read_text())
    errors = []
    if vault["case_id"] != case.data["id"] or vault["version"] != case.data["version"]:
        errors.append("Vault and public case version mismatch")
    if vault["killer_id"] not in case.suspects:
        errors.append("Canonical killer is not a public suspect")
    required = set(vault["required_evidence"])
    if not required <= case.evidence.keys():
        errors.append("Decisive evidence ID missing")
    if set(vault["alternatives"]) != set(case.suspects) - {vault["killer_id"]}:
        errors.append("Alternatives do not cover exactly seven other suspects")
    public = canonical(case.data)
    for key in ("killer_id", "true_timeline", "required_evidence", "red_herrings"):
        if f'"{key}"' in public:
            errors.append(f"Evaluator-only field leaked: {key}")
    accessible = set(case.data["initial_evidence"])
    accessible.update(e["id"] for e in case.timeline())
    accessible.update(e["id"] for suspect in case.suspects for e in case.interview(suspect))
    accessible.update(eid for targets in case.data["forensic_map"].values() for eid in targets)
    for item in case.evidence.values():
        if item["kind"] == "record" and item["id"] in [e["id"] for e in case.search(item["title"], limit=32)]:
            accessible.add(item["id"])
    missing = set(case.evidence) - accessible
    if missing:
        errors.append(f"Inaccessible evidence: {sorted(missing)}")
    if not required <= accessible:
        errors.append("Decisive evidence inaccessible")
    # Hand-authored timeline consistency checks for the decisive sequence.
    for eid, marker in {"E04": "21:43", "E10": "21:42:50", "E11": "21:43:19",
                        "E12": "21:45", "E17": "21:48", "E21": "20:21", "E25": "20:32"}.items():
        if marker not in case.get(eid)["text"]:
            errors.append(f"Timeline marker missing from {eid}")
    return {"valid": not errors, "errors": errors, "case_hash": case.version_hash,
            "suspects": len(case.suspects), "evidence": len(case.evidence)}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
    if not validate()["valid"]:
        raise SystemExit(1)
