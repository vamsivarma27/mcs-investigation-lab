"""Reconstruct observable information flow; edges are facts, not causal proof."""
from __future__ import annotations

import json

from .ledger import Ledger


def build_graph(ledger: Ledger, run_id: str) -> dict:
    with ledger.connect() as db:
        agents = [dict(row) for row in db.execute("SELECT id,role,parent_id FROM agents WHERE run_id=?", (run_id,))]
        messages = [dict(row) for row in db.execute("SELECT * FROM messages WHERE run_id=?", (run_id,))]
        hypotheses = [dict(row) for row in db.execute("SELECT * FROM hypotheses WHERE run_id=?", (run_id,))]
        findings = [dict(row) for row in db.execute("SELECT * FROM findings WHERE run_id=?", (run_id,))]
    events = ledger.events(run_id)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(kind: str, identifier: str, label: str | None = None) -> str:
        key = f"{kind}:{identifier}"
        if key not in nodes or label is not None:
            nodes[key] = {"id": key, "kind": kind, "label": label or identifier}
        return key

    for agent in agents:
        node("agent", agent["id"], agent["role"])
        if agent["parent_id"]:
            edges.append({"from": node("agent", agent["parent_id"]), "to": node("agent", agent["id"]),
                          "type": "DELEGATED"})
    for event in events:
        if event["event_type"] == "EVIDENCE_ACCESSED":
            evidence = node("evidence", event["payload"]["evidence_id"])
            actor = node("agent", event["agent_id"])
            edges.append({"from": actor, "to": evidence, "type": "DISCOVERED",
                          "event_sequence": event["sequence"]})
    for message in messages:
        mid = node("message", message["id"], message["type"])
        edges.extend([{"from": node("agent", message["sender"]), "to": mid, "type": "SENT"},
                      {"from": mid, "to": node("agent", message["recipient"]), "type": "RECEIVED"}])
        for eid in json.loads(message["related_evidence"]):
            edges.append({"from": node("evidence", eid), "to": mid, "type": "CITED"})
    for finding in findings:
        fid = node("finding", finding["id"], finding["text"][:70])
        edges.append({"from": node("agent", finding["agent_id"]), "to": fid, "type": "AUTHORED"})
        for eid in json.loads(finding["evidence"]):
            edges.append({"from": node("evidence", eid), "to": fid, "type": "SUPPORTED"})
    for hypothesis in hypotheses:
        hid = node("hypothesis", hypothesis["id"], f"{hypothesis['suspect_id']} {hypothesis['confidence']:.0%}")
        edges.append({"from": node("agent", hypothesis["agent_id"]), "to": hid, "type": "HELD",
                      "event_sequence": hypothesis["event_sequence"]})
        for eid in json.loads(hypothesis["support"]):
            edges.append({"from": node("evidence", eid), "to": hid, "type": "SUPPORTED"})
        for eid in json.loads(hypothesis["contradict"]):
            edges.append({"from": node("evidence", eid), "to": hid, "type": "CONTRADICTED"})
        if hypothesis["supersedes"]:
            edges.append({"from": node("hypothesis", hypothesis["supersedes"]), "to": hid,
                          "type": "SUPERSEDED"})
    return {"nodes": list(nodes.values()), "edges": edges,
            "note": "Edges show recorded transfers and citations; they do not prove psychological causation."}
