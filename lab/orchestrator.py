from __future__ import annotations

import json
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

from .case import CaseEngine, canonical
from .config import Settings
from .evaluator import Evaluator
from .ledger import Ledger, utcnow
from .provider import MockProvider, ModelProvider, OpenRouterProvider
from .tools import SCHEMAS, ToolDispatcher

TRANSITIONS = {
    "CREATED": "INITIALIZING", "INITIALIZING": "INVESTIGATING",
    "INVESTIGATING": "INDEPENDENT_CONCLUSIONS",
    "INDEPENDENT_CONCLUSIONS": "DELIBERATION", "DELIBERATION": "FINALIZED",
    "FINALIZED": "GROUND_TRUTH_UNSEALED", "GROUND_TRUTH_UNSEALED": "EVALUATING",
    "EVALUATING": "COMPLETED",
}


class Orchestrator:
    def __init__(self, settings: Settings, ledger: Ledger | None = None, case: CaseEngine | None = None,
                 provider: ModelProvider | None = None):
        settings.validate()
        self.settings = settings
        self.ledger = ledger or Ledger(settings.database_path)
        self.case = case or CaseEngine()
        self.provider = provider or (OpenRouterProvider(settings) if settings.provider == "openrouter" else MockProvider())
        self.tools = ToolDispatcher(self.ledger, self.case, settings)
        self.pool = ThreadPoolExecutor(max_workers=2)

    def _git_commit(self) -> str | None:
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    def create(self, lead_count: int = 3) -> str:
        if lead_count not in {2, 3}:
            raise ValueError("lead_count must be 2 or 3")
        run_id = uuid.uuid4().hex
        config = {"provider": self.settings.provider, "investigator_model": self.settings.investigator_model,
                  "decision_model": self.settings.decision_model if self.settings.jev_enabled else None,
                  "jev_enabled": self.settings.jev_enabled, "limits": {
                  "max_model_calls": self.settings.max_model_calls,
                  "max_tools_per_agent": self.settings.max_tools_per_agent,
                  "max_total_agents": self.settings.max_total_agents,
                  "max_workers_per_lead": self.settings.max_workers_per_lead,
                  "max_depth": self.settings.max_depth, "max_cost_usd": self.settings.max_cost_usd},
                  "prompt_version": "investigator-v1", "tool_version": "tools-v1", "scoring_version": "rubric-v1",
                  "case_version": self.case.data["version"], "case_hash": self.case.version_hash,
                  "app_version": "0.1.0", "git_commit": self._git_commit(), "lead_count": lead_count}
        with self.ledger.connect() as db:
            db.execute("INSERT INTO runs (id,phase,created_at,case_hash,config) VALUES (?,?,?,?,?)",
                       (run_id, "CREATED", utcnow(), self.case.version_hash, canonical(config)))
        self.ledger.append(run_id, "RUN_CREATED", {"config": config})
        return run_id

    def start(self, lead_count: int = 3) -> str:
        run_id = self.create(lead_count)
        self.pool.submit(self.execute, run_id)
        return run_id

    def _transition(self, run_id: str, next_phase: str) -> None:
        with self.ledger.connect() as db:
            row = db.execute("SELECT phase FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row or TRANSITIONS.get(row["phase"]) != next_phase:
                raise ValueError(f"Invalid lifecycle transition to {next_phase}")
            db.execute("UPDATE runs SET phase=?, finished_at=CASE WHEN ?='COMPLETED' THEN ? ELSE finished_at END WHERE id=?",
                       (next_phase, next_phase, utcnow(), run_id))
        self.ledger.append(run_id, next_phase, {"from": row["phase"]})

    def _create_leads(self, run_id: str) -> None:
        with self.ledger.connect() as db:
            config = json.loads(db.execute("SELECT config FROM runs WHERE id=?", (run_id,)).fetchone()["config"])
        for i in range(config["lead_count"]):
            aid = uuid.uuid4().hex
            role = f"Lead {i + 1}"
            with self.ledger.connect() as db:
                db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (aid, run_id, None, aid, role, "Investigate independently and report with citations", 0,
                            "active", canonical({"known_evidence": []}), self.settings.investigator_model, utcnow(), None, 0))
            self.ledger.append(run_id, "AGENT_CREATED", {"role": role, "task": "Independent investigation"}, aid)
            self.ledger.append(run_id, "TASK_ASSIGNED", {"task": "Investigate the case and submit an independent accusation"}, aid)

    def _agents(self, run_id: str, leads_only: bool = False) -> list[dict]:
        clause = " AND parent_id IS NULL" if leads_only else ""
        with self.ledger.connect() as db:
            rows = db.execute("SELECT * FROM agents WHERE run_id=?" + clause + " ORDER BY created_at,id", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def _context(self, run_id: str, agent: dict, stage: str) -> dict:
        state = json.loads(agent["private_state"])
        known = state["known_evidence"]
        with self.ledger.connect() as db:
            inbox = [dict(row) for row in db.execute("SELECT * FROM messages WHERE run_id=? AND recipient=? ORDER BY created_at",
                                                     (run_id, agent["id"]))]
            hypotheses = [dict(row) for row in db.execute("SELECT * FROM hypotheses WHERE run_id=? AND agent_id=? ORDER BY event_sequence",
                                                          (run_id, agent["id"]))]
            findings = [dict(row) for row in db.execute("SELECT * FROM findings WHERE run_id=? AND agent_id=?",
                                                       (run_id, agent["id"]))]
            peers = [{"id": row["id"], "role": row["role"]} for row in db.execute(
                "SELECT id,role FROM agents WHERE run_id=? AND parent_id IS NULL", (run_id,))]
        allowed = [name for name in SCHEMAS if stage == "investigation" or
                   (stage == "independent" and name == "submit_final_accusation") or
                   (stage == "deliberation" and name in {"send_message", "request_peer_review", "share_finding", "challenge_hypothesis"}) or
                   (stage == "final" and name == "submit_final_accusation")]
        return {"case": self.case.overview(),
                "agent": {"id": agent["id"], "role": agent["role"], "task": agent["task"],
                          "parent_id": agent["parent_id"], "tool_calls": agent["tool_calls"]},
                "known_evidence": known, "evidence": [self.case.get(eid) for eid in known],
                "inbox": [{**m, "related_evidence": json.loads(m["related_evidence"])} for m in inbox],
                "own_hypotheses": [{**h, "support": json.loads(h["support"]), "contradict": json.loads(h["contradict"])} for h in hypotheses],
                "own_findings": [{**f, "evidence": json.loads(f["evidence"])} for f in findings],
                "peers": peers, "allowed_tools": {name: SCHEMAS[name].model_json_schema() for name in allowed}}

    def _resource_usage(self, run_id: str) -> dict:
        events = self.ledger.events(run_id)
        responses = [e for e in events if e["event_type"] in {"MODEL_RESPONSE", "JEV_DECISION"}]
        requests = [e for e in events if e["event_type"] in {"MODEL_REQUEST", "JEV_REQUEST"}]
        return {"model_calls": len(requests),
                "input_tokens": sum(e["payload"].get("usage", {}).get("prompt_tokens",
                    e["payload"].get("usage", {}).get("input_tokens", 0)) for e in responses),
                "output_tokens": sum(e["payload"].get("usage", {}).get("completion_tokens",
                    e["payload"].get("usage", {}).get("output_tokens", 0)) for e in responses),
                "cost_usd": round(sum(e["payload"].get("cost") or 0 for e in responses), 6)}

    def _turn(self, run_id: str, agent_id: str, stage: str) -> None:
        agent = next(a for a in self._agents(run_id) if a["id"] == agent_id)
        if agent["status"] != "active":
            return
        usage = self._resource_usage(run_id)
        if usage["model_calls"] >= self.settings.max_model_calls or usage["cost_usd"] >= self.settings.max_cost_usd:
            self.ledger.append(run_id, "BUDGET_EXHAUSTED", usage, agent_id)
            return
        context = self._context(run_id, agent, stage)
        if self.settings.jev_enabled and stage == "investigation" and isinstance(self.provider, OpenRouterProvider):
            try:
                self.ledger.append(run_id, "JEV_REQUEST", {"model": self.settings.decision_model,
                    "state": {"role": agent["role"], "known_evidence": context["known_evidence"],
                              "task": agent["task"]}}, agent_id)
                recommendation = self.provider.choose_action({"role": agent["role"],
                    "known_evidence": context["known_evidence"], "task": agent["task"]}, list(context["allowed_tools"]))
                context["jev_recommendation"] = recommendation["choice"]
                self.ledger.append(run_id, "JEV_DECISION", recommendation, agent_id)
            except Exception as exc:  # noqa: BLE001 - audit and contain model/runtime failures
                self.ledger.append(run_id, "JEV_ERROR", {"error": str(exc)[:300]}, agent_id)
        attempts = 3 if stage in {"independent", "final"} else 2
        for attempt in range(attempts):
            usage = self._resource_usage(run_id)
            if usage["model_calls"] >= self.settings.max_model_calls or usage["cost_usd"] >= self.settings.max_cost_usd:
                self.ledger.append(run_id, "BUDGET_EXHAUSTED", usage, agent_id)
                return
            self.ledger.append(run_id, "MODEL_REQUEST", {"stage": stage, "model": agent["model"],
                "attempt": attempt + 1, "context": context}, agent_id)
            try:
                response = self.provider.decide(context, stage)
                if response.action.tool not in context["allowed_tools"]:
                    self.ledger.append(run_id, "MODEL_INVALID_OUTPUT", {"tool": response.action.tool,
                                               "reason": "Action outside stage allowlist"}, agent_id)
                    raise ValueError("Action outside stage allowlist")
                self.ledger.append(run_id, "MODEL_RESPONSE", {"stage": stage, "model": response.model,
                    "provider": response.provider, "action": response.action.model_dump(),
                    "usage": response.usage, "cost": response.cost, "latency_ms": response.latency_ms}, agent_id)
                result = self.tools.dispatch(run_id, agent_id, response.action.tool, response.action.args)
                if result.get("denied"):
                    self.ledger.append(run_id, "POLICY_DENIAL", {"tool": response.action.tool, "reason": result["error"]}, agent_id)
                return
            except Exception as exc:  # noqa: BLE001 - audit and contain model/runtime failures
                self.ledger.append(run_id, "MODEL_ERROR", {"attempt": attempt + 1, "error": str(exc)[:500]}, agent_id)
                if attempt + 1 < attempts:
                    self.ledger.append(run_id, "MODEL_RETRY", {"attempt": attempt + 2}, agent_id)
        if stage in {"independent", "final"}:
            self.ledger.append(run_id, "ACCUSATION_MISSING", {"stage": stage}, agent_id)

    def execute(self, run_id: str) -> None:
        try:
            self._transition(run_id, "INITIALIZING")
            self._create_leads(run_id)
            self._transition(run_id, "INVESTIGATING")
            for _ in range(7):
                for agent in self._agents(run_id):
                    if agent["tool_calls"] < self.settings.max_tools_per_agent:
                        self._turn(run_id, agent["id"], "investigation")
            self._transition(run_id, "INDEPENDENT_CONCLUSIONS")
            for agent in self._agents(run_id, leads_only=True):
                self._turn(run_id, agent["id"], "independent")
            self._require_accusations(run_id, "independent")
            self._transition(run_id, "DELIBERATION")
            for agent in self._agents(run_id, leads_only=True):
                self._turn(run_id, agent["id"], "deliberation")
            for agent in self._agents(run_id, leads_only=True):
                self._turn(run_id, agent["id"], "final")
            self._require_accusations(run_id, "final")
            self._transition(run_id, "FINALIZED")
            self.ledger.append(run_id, "RUN_FINALIZED", {})
            self._transition(run_id, "GROUND_TRUTH_UNSEALED")
            self.ledger.append(run_id, "GROUND_TRUTH_UNSEALED", {})
            self._transition(run_id, "EVALUATING")
            result = Evaluator(self.ledger, self.case).evaluate(run_id)
            with self.ledger.connect() as db:
                db.execute("INSERT INTO evaluations VALUES (?,?)", (run_id, canonical(result)))
            self.ledger.append(run_id, "EVALUATION_COMPLETED", {"scores": [{"agent_id": a["agent_id"],
                "quality_score": a["quality_score"], "killer_accuracy": a["killer_accuracy"]} for a in result["agents"]]})
            for agent in self._agents(run_id):
                with self.ledger.connect() as db:
                    db.execute("UPDATE agents SET status='terminated',terminated_at=? WHERE id=?", (utcnow(), agent["id"]))
            self._transition(run_id, "COMPLETED")
        except Exception as exc:
            with self.ledger.connect() as db:
                db.execute("UPDATE runs SET phase='FAILED',error=?,finished_at=? WHERE id=?", (str(exc)[:500], utcnow(), run_id))
            self.ledger.append(run_id, "RUN_FAILED", {"error": str(exc)[:500]})
            raise

    def _require_accusations(self, run_id: str, stage: str) -> None:
        with self.ledger.connect() as db:
            leads = db.execute(
                "SELECT COUNT(*) AS n FROM agents WHERE run_id=? AND parent_id IS NULL", (run_id,)
            ).fetchone()["n"]
            accusations = db.execute(
                "SELECT COUNT(*) AS n FROM accusations WHERE run_id=? AND stage=?", (run_id, stage)
            ).fetchone()["n"]
        if accusations != leads:
            raise RuntimeError(
                f"Cannot continue: {accusations}/{leads} leads submitted {stage} accusations"
            )

    def snapshot(self, run_id: str) -> dict:
        with self.ledger.connect() as db:
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise KeyError(run_id)
            evaluation = db.execute("SELECT result FROM evaluations WHERE run_id=?", (run_id,)).fetchone()
            messages = [dict(row) for row in db.execute("SELECT * FROM messages WHERE run_id=? ORDER BY created_at", (run_id,))]
            hypotheses = [dict(row) for row in db.execute("SELECT * FROM hypotheses WHERE run_id=? ORDER BY event_sequence", (run_id,))]
            accusations = [dict(row) for row in db.execute("SELECT * FROM accusations WHERE run_id=?", (run_id,))]
        agents = self._agents(run_id)
        for a in agents:
            a["private_state"] = json.loads(a["private_state"])
        for m in messages:
            m["related_evidence"] = json.loads(m["related_evidence"])
        for h in hypotheses:
            h["support"] = json.loads(h["support"])
            h["contradict"] = json.loads(h["contradict"])
        for a in accusations:
            a["report"] = json.loads(a["report"])
        return {"run": {**dict(run), "config": json.loads(run["config"])}, "agents": agents,
                "messages": messages, "hypotheses": hypotheses, "accusations": accusations,
                "evaluation": json.loads(evaluation["result"]) if evaluation else None,
                "usage": self._resource_usage(run_id), "audit": self.ledger.verify(run_id)}
