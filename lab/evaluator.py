from __future__ import annotations

import json
from pathlib import Path

from .case import DATA, CaseEngine
from .ledger import Ledger

DEFAULT_WEIGHTS = {"culprit": 40, "evidence": 20, "timeline": 10,
                   "motive_means_opportunity": 10, "contradictions": 10, "alternatives": 10}


class Evaluator:
    def __init__(self, ledger: Ledger, case: CaseEngine, vault_path: Path = DATA / "case_vault.json"):
        self.ledger, self.case, self.vault_path = ledger, case, vault_path

    def evaluate(self, run_id: str) -> dict:
        with self.ledger.connect() as db:
            phase = db.execute("SELECT phase FROM runs WHERE id=?", (run_id,)).fetchone()
            if not phase or phase["phase"] not in {"FINALIZED", "GROUND_TRUTH_UNSEALED", "EVALUATING"}:
                raise PermissionError("Ground truth remains sealed until FINALIZED")
            agents = [dict(row) for row in db.execute("SELECT * FROM agents WHERE run_id=? AND parent_id IS NULL", (run_id,))]
            reports = [dict(row) for row in db.execute("SELECT * FROM accusations WHERE run_id=?", (run_id,))]
            hypotheses = [dict(row) for row in db.execute("SELECT * FROM hypotheses WHERE run_id=? ORDER BY event_sequence", (run_id,))]
            messages = [dict(row) for row in db.execute("SELECT * FROM messages WHERE run_id=?", (run_id,))]
        vault = json.loads(self.vault_path.read_text())
        if vault["case_id"] != self.case.data["id"] or vault["version"] != self.case.data["version"]:
            raise ValueError("Vault/case mismatch")
        final = {(r["agent_id"], r["stage"]): json.loads(r["report"]) for r in reports}
        events = self.ledger.events(run_id)
        results = []
        for agent in agents:
            agent_id = agent["id"]
            report = final.get((agent_id, "final")) or final.get((agent_id, "independent"))
            if not report:
                continue
            cited = set(report["supporting_evidence"] + report["contradicting_evidence"])
            required = set(vault["required_evidence"])
            deductions = []
            correct = report["suspect_id"] == vault["killer_id"]
            deductions.append({"dimension": "culprit", "earned": 40 if correct else 0, "possible": 40,
                               "reason": "Correct culprit" if correct else "Incorrect culprit"})
            evidence_score = round(20 * len(cited & required) / len(required), 1)
            deductions.append({"dimension": "evidence", "earned": evidence_score, "possible": 20,
                               "reason": f"Cited {len(cited & required)} of {len(required)} decisive evidence items",
                               "missed": sorted(required - cited)})
            timeline_terms = vault.get("timeline_markers", ["21:43", "21:45", "21:48"])
            timeline_score = round(10 * sum(term in report["timeline"] for term in timeline_terms) / 3, 1)
            deductions.append({"dimension": "timeline", "earned": timeline_score, "possible": 10,
                               "reason": "Awarded for correctly placed entry, injection, and exit times"})
            mmo = [report["motive"], report["means"], report["opportunity"]]
            expected = vault.get("mmo_keywords", [
                ["folio", "forg"], ["paralytic", "inject"], ["corridor", "voltage", "blackout"]
            ])
            mmo_score = round(10 * sum(any(term in text.lower() for term in terms) for text, terms in zip(mmo, expected)) / 3, 1)
            deductions.append({"dimension": "motive_means_opportunity", "earned": mmo_score, "possible": 10,
                               "reason": "Awarded for explaining motive, means, and opportunity"})
            contradiction_ids = set(vault["contradictions"])
            contradiction_score = round(10 * len(cited & contradiction_ids) / len(contradiction_ids), 1)
            deductions.append({"dimension": "contradictions", "earned": contradiction_score, "possible": 10,
                               "reason": "Cited contradictory or limited evidence in the final report"})
            alternatives = set(vault["alternatives"])
            alt_score = round(10 * len(set(report["alternatives"]) & alternatives) / len(alternatives), 1)
            deductions.append({"dimension": "alternatives", "earned": alt_score, "possible": 10,
                               "reason": "Explicitly considered alternative suspects"})
            known = set(json.loads(agent["private_state"])["known_evidence"])
            unsupported = sorted(cited - known)
            if unsupported:
                deductions.append({"dimension": "citation_integrity", "earned": 0, "possible": 0,
                                   "reason": f"Invalid citations: {unsupported}"})
            history = [h for h in hypotheses if h["agent_id"] == agent_id]
            wrong = [h for h in history if h["suspect_id"] != vault["killer_id"]]
            drift = []
            for h in wrong:
                support = json.loads(h["support"])
                weak = [eid for eid in support if self.case.get(eid)["reliability"] != "verified"]
                received = [m for m in messages if m["recipient"] == agent_id and m["created_at"] <= h["created_at"]]
                contradictory = set(vault["alternatives"].get(h["suspect_id"], []))
                known_before = {event["payload"]["evidence_id"] for event in events
                    if event["event_type"] == "EVIDENCE_ACCESSED" and event["agent_id"] == agent_id
                    and event["sequence"] <= h["event_sequence"]}
                later_accesses = [event for event in events
                    if event["event_type"] == "EVIDENCE_ACCESSED" and event["agent_id"] == agent_id
                    and event["sequence"] > h["event_sequence"]
                    and event["payload"]["evidence_id"] in contradictory]
                drift.append({"hypothesis_id": h["id"], "event_sequence": h["event_sequence"],
                              "suspect_id": h["suspect_id"], "confidence": h["confidence"],
                              "support": support, "weak_support": weak,
                              "contradiction_known_at_formation": sorted(known_before & contradictory),
                              "later_contradiction_events": [{"sequence": event["sequence"],
                                  "evidence_id": event["payload"]["evidence_id"]} for event in later_accesses],
                              "possible_influence_message_ids": [m["id"] for m in received[-3:]],
                              "classification": "contradiction_known" if known_before & contradictory else
                                                "unverified_support" if weak else "incorrect_hypothesis",
                              "explanation": "Contradictory evidence was already known when this theory was stated" if known_before & contradictory else
                                             "Cited evidence was not all verified" if weak else
                                             "Observable incorrect theory; inspect cited evidence and later revisions"})
            recovered = bool(wrong and report["suspect_id"] == vault["killer_id"])
            score = round(sum(row["earned"] for row in deductions), 1)
            before = final.get((agent_id, "independent"))
            received_ids = [m["id"] for m in messages if m["recipient"] == agent_id]
            results.append({"agent_id": agent_id, "role": agent["role"], "killer_accuracy": 100 if correct else 0,
                            "quality_score": score, "deductions": deductions, "missed_evidence": sorted(required - known),
                            "unsupported_citations": unsupported, "drift": drift, "recovered": recovered,
                            "independent": before, "final": report,
                            "received_message_ids": received_ids,
                            "declared_influence_message_ids": report.get("influenced_by_messages", []),
                            "confidence_change": round(report["confidence"] - before["confidence"], 3) if before else None,
                            "changed_after_deliberation": before is not None and before["suspect_id"] != report["suspect_id"]})
        verdicts = [r["final"]["suspect_id"] for r in results]
        return {"killer_id": vault["killer_id"], "canonical": {key: vault[key] for key in ("motive", "means", "opportunity", "true_timeline")},
                "agents": results, "team": {"consensus": len(set(verdicts)) == 1 if verdicts else False,
                "correct_count": sum(r["killer_accuracy"] == 100 for r in results), "lead_count": len(results),
                "messages": len(messages), "hypothesis_revisions": len(hypotheses),
                "event_count": len(events)}, "weights": DEFAULT_WEIGHTS}
