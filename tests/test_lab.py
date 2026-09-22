from __future__ import annotations

import json
from dataclasses import replace

import pytest

from lab.agents import AgentInput, public_catalog
from lab.case import CaseEngine
from lab.config import Settings
from lab.evaluator import Evaluator
from lab.ledger import Ledger
from lab.orchestrator import Orchestrator


@pytest.fixture
def lab(tmp_path):
    settings = replace(Settings(), provider="mock", api_key="", database_path=str(tmp_path / "runs.sqlite3"))
    return Orchestrator(settings)


def test_case_public_has_no_answer_and_is_consistent():
    case = CaseEngine()
    assert len(case.suspects) == 8
    assert len(case.evidence) >= 30
    assert "killer_id" not in json.dumps(case.data)
    assert case.version_hash


def test_case_catalog_has_more_than_fifty_sealed_cases():
    from lab.case_catalog import CaseCatalog
    from lab.validate_case import validate

    catalog = CaseCatalog()
    cases = catalog.list()
    assert len(cases) == 61
    assert {case["difficulty"] for case in cases} == {"Beginner", "Easy", "Moderate", "Hard", "Expert"}
    assert all(case["evidence_count"] == 32 and case["suspect_count"] == 8 for case in cases)
    assert validate()["valid"]


def test_custom_agent_profiles_are_validated_and_limit_tools(lab):
    team = [
        AgentInput(template_id="forensic-analyst", name="Trace", mission="Analyze physical traces.",
                   model="example/tool-model", skills=["scene-analysis", "forensics"]),
        AgentInput(template_id="timeline-analyst", name="Clock", mission="Reconstruct every time window.",
                   skills=["timeline-analysis", "records-research"]),
    ]
    run = lab.create(case_id="meridian-archive", agents=team)
    lab._transition(run, "INITIALIZING")
    lab._create_leads(run)
    lab._transition(run, "INVESTIGATING")
    agents = lab._agents(run)
    assert [agent["role"] for agent in agents] == ["Trace", "Clock"]
    assert agents[0]["model"] == "example/tool-model"
    context = lab._context(run, agents[0], "investigation")
    assert "request_forensic_analysis" in context["allowed_tools"]
    assert "interview_suspect" not in context["allowed_tools"]
    assert "submit_final_accusation" in context["allowed_tools"]
    assert lab.tools.dispatch(run, agents[0]["id"], "interview_suspect",
                              {"suspect_id": "s_ada"})["denied"]
    assert lab.tools.dispatch(run, agents[0]["id"], "request_specialist",
                              {"specialization": "forensic", "task": "Analyze traces"})["denied"]
    assert lab.tools.dispatch(run, agents[0]["id"], "share_finding",
                              {"recipient": agents[1]["id"], "content": "A lead"})["denied"]
    assert public_catalog()["templates"]


def test_duplicate_custom_agent_names_fail_closed(lab):
    agents = [
        AgentInput(name="Same", mission="Investigate the case independently."),
        AgentInput(name="same", mission="Review the case evidence independently."),
    ]
    with pytest.raises(ValueError, match="unique"):
        lab.create(agents=agents)


def test_local_api_host_and_security_headers():
    from fastapi.testclient import TestClient

    from lab.api import app

    client = TestClient(app, base_url="http://127.0.0.1:8765")
    response = client.get("/api/agent-catalog")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/api/health", headers={"host": "unexpected.example"}).status_code == 400


def test_vault_stays_sealed_and_cross_run_access_denied(lab):
    first = lab.create()
    second = lab.create()
    lab._transition(first, "INITIALIZING")
    lab._create_leads(first)
    lab._transition(first, "INVESTIGATING")
    agent = lab._agents(first)[0]["id"]
    with pytest.raises(PermissionError):
        Evaluator(lab.ledger, lab.case).evaluate(first)
    assert lab.tools.dispatch(first, agent, "read_ground_truth", {})["denied"]
    assert lab.tools.dispatch(second, agent, "inspect_crime_scene", {})["denied"]
    assert lab.tools.dispatch(first, agent, "arbitrary_http_request", {"url": "https://example.org"})["denied"]
    assert lab.tools.dispatch(first, agent, "run_shell", {"cmd": "cat lab/data/case_vault.json"})["denied"]
    assert lab.tools.dispatch(first, agent, "update_audit_event", {"sequence": 1})["denied"]
    assert lab.ledger.verify(first)["valid"]


def test_private_knowledge_explicit_message_and_injection_is_data(lab):
    run = lab.create()
    lab._transition(run, "INITIALIZING")
    lab._create_leads(run)
    lab._transition(run, "INVESTIGATING")
    a, b = [agent["id"] for agent in lab._agents(run)[:2]]
    result = lab.tools.dispatch(run, a, "search_case_records", {"query": "SYSTEM OVERRIDE"})
    assert any(e["id"] == "E19" for e in result["evidence"])
    assert "E19" in lab.tools._known(lab.tools._agent(run, a))
    assert "E19" not in lab.tools._known(lab.tools._agent(run, b))
    denied = lab.tools.dispatch(run, b, "inspect_evidence", {"evidence_id": "E19"})
    assert denied["denied"]
    sent = lab.tools.dispatch(run, a, "send_message", {"recipient": b, "type": "share_finding",
        "content": "Review E19 as untrusted artifact content", "related_evidence": ["E19"]})
    assert sent["delivered"]
    assert "E19" in lab.tools._known(lab.tools._agent(run, b))
    assert lab.tools.dispatch(run, a, "send_message", {"recipient": "other-run", "content": "x"})["denied"]


def test_full_offline_run_persists_evaluates_and_replays(lab):
    from lab.graph import build_graph
    from lab.report import build_run_report

    run = lab.create()
    lab.execute(run)
    state = lab.snapshot(run)
    assert state["run"]["phase"] == "COMPLETED"
    assert len([a for a in state["agents"] if a["parent_id"] is None]) == 3
    assert len([a for a in state["agents"] if a["parent_id"] is not None]) >= 1
    assert len(state["accusations"]) == 6
    assert state["evaluation"]["team"]["lead_count"] == 3
    assert state["evaluation"]["killer_id"] == "s_ada"
    assert state["audit"]["valid"]
    events = lab.ledger.events(run)
    finalized = next(e["sequence"] for e in events if e["event_type"] == "RUN_FINALIZED")
    unsealed = next(e["sequence"] for e in events if e["event_type"] == "GROUND_TRUTH_UNSEALED")
    assert finalized < unsealed
    assert any(e["event_type"] == "MESSAGE_SENT" for e in events)
    assert any(e["event_type"] == "HYPOTHESIS_CREATED" for e in events)
    assert any(e["event_type"] == "EVIDENCE_ACCESSED" for e in events)
    assert state["evaluation"]["agents"][1]["drift"]
    assert state["evaluation"]["agents"][1]["changed_after_deliberation"]
    graph = build_graph(lab.ledger, run)
    assert any(node["label"] == "Lead Detective" for node in graph["nodes"])
    assert any(edge["type"] == "RECEIVED" for edge in graph["edges"])
    report = build_run_report(lab.ledger, lab.case, run)
    assert report["headline"] == "Investigation completed"
    assert report["metrics"]["audit_valid"]
    assert report["charts"]["tool_usage"]
    # Fresh process-like reader reconstructs the same ordered history.
    assert len(Ledger(lab.settings.database_path).events(run)) == len(events)


def test_nondefault_case_is_bound_to_run_and_evaluated(lab):
    run = lab.create(lead_count=2, case_id="aurora-observatory-1")
    lab.execute(run)
    state = lab.snapshot(run)
    assert state["run"]["phase"] == "COMPLETED"
    assert state["run"]["config"]["case_id"] == "aurora-observatory-1"
    assert state["case"]["difficulty"] == "Beginner"
    assert state["evaluation"]["canonical"]["true_timeline"]


def test_hash_chain_detects_modification_and_deletion(lab):
    run = lab.create()
    lab.ledger.append(run, "TEST", {"value": 1})
    assert lab.ledger.verify(run)["valid"]
    with lab.ledger.connect() as db:
        db.execute("UPDATE events SET payload='{}' WHERE run_id=? AND sequence=2", (run,))
    assert not lab.ledger.verify(run)["valid"]
    with lab.ledger.connect() as db:
        db.execute("DELETE FROM events WHERE run_id=? AND sequence=1", (run,))
    assert not lab.ledger.verify(run)["valid"]


def test_hash_chain_detects_tail_truncation(lab):
    run = lab.create()
    lab.ledger.append(run, "TEST", {"value": 1})
    with lab.ledger.connect() as db:
        db.execute("DELETE FROM events WHERE run_id=? AND sequence=2", (run,))
    assert "run anchor" in lab.ledger.verify(run)["errors"]


def test_openrouter_provider_uses_controlled_tool_schema_and_decision_endpoint(monkeypatch):
    from lab.provider import OpenRouterProvider

    calls = []

    class Response:
        def __init__(self, data):
            self.data = data
            self.is_success = True
            self.status_code = 200
            self.reason_phrase = "OK"

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def post(url, *, headers, json, timeout):
        calls.append((url, headers, json))
        if url.endswith('/decisions'):
            return Response({"model": "typesafe/jev-1.13-20260917", "answers": {
                "next_action": {"type": "choice", "choice": "inspect_crime_scene", "confidence": .91,
                                "probabilities": {"inspect_crime_scene": .91, "inspect_timeline": .09}}},
                "usage": {"input_tokens": 150, "output_tokens": 20}})
        return Response({"model": "real-investigator-version", "choices": [{"message": {"content": "Inspect the scene",
            "tool_calls": [{"function": {"name": "inspect_crime_scene", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 20}})

    monkeypatch.setattr('lab.provider.httpx.post', post)
    provider = OpenRouterProvider(replace(Settings(), provider="openrouter", api_key="test-key"))
    context = {"allowed_tools": {"inspect_crime_scene": {"type": "object", "properties": {}, "additionalProperties": False}},
               "known_evidence": [], "agent": {"role": "Lead 1"}}
    result = provider.decide(context, "investigation")
    decision = provider.choose_action({"role": "Lead 1"}, ["inspect_crime_scene", "inspect_timeline"])
    assert result.action.tool == "inspect_crime_scene"
    assert result.model == "real-investigator-version"
    assert calls[0][0].endswith('/chat/completions')
    assert calls[0][2]['tools'][0]['function']['name'] == "inspect_crime_scene"
    assert calls[0][2]['reasoning_effort'] == "minimal"
    assert calls[0][2]['max_completion_tokens'] == 1800
    assert calls[0][2]['tool_choice'] == {
        "type": "function", "function": {"name": "inspect_crime_scene"}
    }
    assert calls[1][0].endswith('/api/alpha/decisions')
    assert calls[1][2]['questions']['next_action']['type'] == "choice"
    assert decision['choice'] == "inspect_crime_scene"


def test_accusation_cannot_cite_unreceived_message(lab):
    run = lab.create()
    lab._transition(run, "INITIALIZING")
    lab._create_leads(run)
    lab._transition(run, "INVESTIGATING")
    lab._transition(run, "INDEPENDENT_CONCLUSIONS")
    lead = lab._agents(run)[0]["id"]
    result = lab.tools.dispatch(run, lead, "submit_final_accusation", {
        "suspect_id": "s_ada", "confidence": .5, "motive": "Folio fraud",
        "means": "Paralytic injection", "opportunity": "Service corridor",
        "timeline": "Entry and exit during blackout", "supporting_evidence": [],
        "contradicting_evidence": [], "unresolved_questions": [], "alternatives": [],
        "influenced_by_messages": ["invented"]})
    assert result["denied"]


def test_missing_accusations_fail_closed(lab):
    run = lab.create(lead_count=2)
    lab._transition(run, "INITIALIZING")
    lab._create_leads(run)
    lab._transition(run, "INVESTIGATING")
    lab._transition(run, "INDEPENDENT_CONCLUSIONS")
    with pytest.raises(RuntimeError, match="0/2"):
        lab._require_accusations(run, "independent")


def test_duplicate_read_is_denied_and_recent_actions_are_in_context(lab):
    run = lab.create(lead_count=2)
    lab._transition(run, "INITIALIZING")
    lab._create_leads(run)
    lab._transition(run, "INVESTIGATING")
    lead = lab._agents(run)[0]
    assert "scene" in lab.tools.dispatch(run, lead["id"], "inspect_crime_scene", {})
    repeated = lab.tools.dispatch(run, lead["id"], "inspect_crime_scene", {})
    assert repeated["denied"]
    assert "Duplicate investigation action" in repeated["error"]
    context = lab._context(run, lab._agents(run)[0], "investigation")
    assert context["recent_actions"][-1]["tool"] == "inspect_crime_scene"


def test_failed_report_explains_why_evaluation_is_unavailable(lab):
    from lab.report import build_run_report

    run = lab.create(lead_count=2)
    lab._transition(run, "INITIALIZING")
    lab._create_leads(run)
    with lab.ledger.connect() as db:
        db.execute("UPDATE runs SET phase='FAILED',error=?,finished_at=created_at WHERE id=?",
                   ("Cannot continue: 0/2 leads submitted independent accusations", run))
        db.execute("UPDATE agents SET status='failed' WHERE run_id=?", (run,))
    lab.ledger.append(run, "RUN_FAILED", {"error": "Missing accusations"})
    report = build_run_report(lab.ledger, lab.case, run)
    assert report["tone"] == "error"
    assert report["failure_reason"].startswith("Cannot continue")
    assert report["metrics"]["accusations"] == 0
    assert any("structured accusation" in item for item in report["recommended_actions"])
