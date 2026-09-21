from __future__ import annotations

import json
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .case import CaseEngine, canonical
from .config import Settings
from .ledger import Ledger, utcnow


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


EvidenceRef = Annotated[str, Field(pattern=r"^E\d{2}$")]
SuspectRef = Annotated[str, Field(pattern=r"^s_[a-z]+$")]


class Empty(Strict):
    pass


class EvidenceId(Strict):
    evidence_id: str = Field(pattern=r"^E\d{2}$")


class SuspectId(Strict):
    suspect_id: str = Field(pattern=r"^s_[a-z]+$")


class Search(Strict):
    query: str = Field(min_length=2, max_length=120)


class FindingInput(Strict):
    text: str = Field(min_length=5, max_length=2000)
    evidence: list[EvidenceRef] = Field(max_length=12)


class HypothesisInput(Strict):
    suspect_id: SuspectRef
    claim: str = Field(min_length=5, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: list[EvidenceRef] = Field(max_length=12)
    contradicting_evidence: list[EvidenceRef] = Field(max_length=12)
    reason_for_change: str = Field(min_length=3, max_length=1000)


class ChallengeInput(Strict):
    hypothesis_id: str
    reason: str = Field(min_length=5, max_length=1000)
    evidence: list[EvidenceRef] = Field(max_length=8)


class SpecialistInput(Strict):
    specialization: Literal["forensic", "evidence", "suspect", "interview", "timeline", "contradiction"]
    task: str = Field(min_length=5, max_length=300)


class TaskInput(Strict):
    recipient: str
    task: str = Field(min_length=5, max_length=300)


class MessageInput(Strict):
    recipient: str
    type: Literal["send_message", "share_finding", "request_review", "challenge_agent", "request_information", "task_handoff"] = "send_message"
    content: str = Field(min_length=1, max_length=2000)
    related_evidence: list[EvidenceRef] = Field(default_factory=list, max_length=12)
    related_task: str | None = Field(default=None, max_length=300)


class AccusationInput(Strict):
    suspect_id: SuspectRef = Field(description="Exactly one suspect ID from the supplied suspect list")
    confidence: float = Field(ge=0, le=1)
    motive: str = Field(min_length=3, max_length=1500)
    means: str = Field(min_length=3, max_length=1500)
    opportunity: str = Field(min_length=3, max_length=1500)
    timeline: str = Field(min_length=3, max_length=2000)
    supporting_evidence: list[EvidenceRef] = Field(
        max_length=20, description="Only known evidence IDs such as E01; never prose"
    )
    contradicting_evidence: list[EvidenceRef] = Field(
        max_length=20, description="Only known evidence IDs such as E02; never prose"
    )
    unresolved_questions: list[str] = Field(max_length=10)
    alternatives: list[SuspectRef] = Field(
        max_length=7, description="Only alternative suspect IDs from the supplied suspect list"
    )
    change_reason: str = Field(default="", max_length=1000)
    influenced_by_messages: list[str] = Field(default_factory=list, max_length=12)


SCHEMAS = {
    "inspect_crime_scene": Empty, "inspect_evidence": EvidenceId,
    "request_forensic_analysis": EvidenceId, "interview_suspect": SuspectId,
    "search_case_records": Search, "inspect_timeline": Empty,
    "submit_finding": FindingInput, "submit_hypothesis": HypothesisInput,
    "challenge_hypothesis": ChallengeInput, "request_specialist": SpecialistInput,
    "create_investigation_task": TaskInput, "send_message": MessageInput,
    "request_peer_review": MessageInput, "share_finding": MessageInput,
    "submit_final_accusation": AccusationInput,
}


class PolicyError(ValueError):
    pass


class ToolDispatcher:
    def __init__(self, ledger: Ledger, case: CaseEngine, settings: Settings):
        self.ledger, self.case, self.settings = ledger, case, settings

    def _agent(self, run_id: str, agent_id: str) -> dict:
        with self.ledger.connect() as db:
            row = db.execute("SELECT * FROM agents WHERE id=? AND run_id=?", (agent_id, run_id)).fetchone()
        if not row:
            raise PolicyError("Unknown agent in this run")
        result = dict(row)
        result["private_state"] = json.loads(result["private_state"])
        return result

    def _phase(self, run_id: str) -> str:
        with self.ledger.connect() as db:
            row = db.execute("SELECT phase FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise PolicyError("Unknown run")
        return row["phase"]

    def _known(self, agent: dict) -> set[str]:
        return set(agent["private_state"].get("known_evidence", []))

    def _grant(self, run_id: str, agent: dict, items: list[dict], source: str) -> list[dict]:
        known = self._known(agent)
        new = []
        for item in items:
            if item["id"] not in known:
                known.add(item["id"])
                new.append(item["id"])
                self.ledger.append(run_id, "EVIDENCE_ACCESSED", {"evidence_id": item["id"], "source": source}, agent["id"])
        state = agent["private_state"]
        state["known_evidence"] = sorted(known)
        with self.ledger.connect() as db:
            db.execute("UPDATE agents SET private_state=? WHERE id=?", (canonical(state), agent["id"]))
        return [{"id": e["id"], "title": e["title"], "kind": e["kind"],
                 "text": e["text"], "reliability": e["reliability"]} for e in items]

    def _require_known(self, agent: dict, ids: list[str]) -> None:
        if not set(ids) <= self._known(agent):
            raise PolicyError("Cited evidence is not known to this agent")

    def dispatch(self, run_id: str, agent_id: str, tool: str, raw_args: dict) -> dict:
        self.ledger.append(run_id, "TOOL_REQUEST", {"tool": tool, "args": raw_args}, agent_id)
        try:
            agent = self._agent(run_id, agent_id)
            phase = self._phase(run_id)
            if phase not in {"INVESTIGATING", "INDEPENDENT_CONCLUSIONS", "DELIBERATION"}:
                raise PolicyError("Investigation is not active")
            if tool not in SCHEMAS:
                raise PolicyError("Unknown tool")
            if agent["status"] != "active":
                raise PolicyError("Agent is not active")
            if agent["tool_calls"] >= self.settings.max_tools_per_agent:
                raise PolicyError("Agent tool budget exhausted")
            if phase == "INDEPENDENT_CONCLUSIONS" and tool != "submit_final_accusation":
                raise PolicyError("Only independent accusation is allowed in this phase")
            if phase == "DELIBERATION" and tool == "submit_final_accusation":
                stage = "final"
            elif phase == "INDEPENDENT_CONCLUSIONS":
                stage = "independent"
            else:
                stage = "investigation"
            args = SCHEMAS[tool].model_validate(raw_args)
            if tool == "submit_final_accusation" and phase == "INVESTIGATING":
                raise PolicyError("Final accusation is premature")
            if tool != "submit_final_accusation" and phase == "DELIBERATION" and tool not in {"send_message", "request_peer_review", "share_finding", "challenge_hypothesis"}:
                raise PolicyError("Only deliberation communication is allowed")
            self.ledger.append(run_id, "TOOL_ALLOWED", {"tool": tool}, agent_id)
            result = self._execute(run_id, agent, tool, args, stage)
            with self.ledger.connect() as db:
                db.execute("UPDATE agents SET tool_calls=tool_calls+1 WHERE id=?", (agent_id,))
            self.ledger.append(run_id, "TOOL_RESULT", {"tool": tool, "result": result}, agent_id)
            return result
        except (PolicyError, ValidationError, KeyError, ValueError) as exc:
            reason = str(exc)[:500]
            self.ledger.append(run_id, "TOOL_DENIED", {"tool": tool, "reason": reason}, agent_id)
            return {"error": reason, "denied": True}

    def _execute(self, run_id: str, agent: dict, tool: str, args: Strict, stage: str) -> dict:
        if tool == "inspect_crime_scene":
            return {"scene": self.case.data["scene"], "evidence": self._grant(run_id, agent,
                [self.case.get(eid) for eid in self.case.data["initial_evidence"]], tool)}
        if tool == "inspect_evidence":
            if args.evidence_id not in self.case.evidence:
                raise PolicyError("Unknown evidence")
            if args.evidence_id not in self._known(agent):
                raise PolicyError("Evidence ID has not been discovered by this agent")
            return {"evidence": self._grant(run_id, agent, [self.case.get(args.evidence_id)], tool)}
        if tool == "request_forensic_analysis":
            self._require_known(agent, [args.evidence_id])
            related = self.case.data["forensic_map"].get(args.evidence_id, [])
            self.ledger.append(run_id, "FORENSIC_REQUESTED", {"evidence_id": args.evidence_id}, agent["id"])
            return {"evidence": self._grant(run_id, agent, [self.case.get(eid) for eid in related], tool)}
        if tool == "interview_suspect":
            if args.suspect_id not in self.case.suspects:
                raise PolicyError("Unknown suspect")
            self.ledger.append(run_id, "INTERVIEW_STARTED", {"suspect_id": args.suspect_id}, agent["id"])
            items = self._grant(run_id, agent, self.case.interview(args.suspect_id), tool)
            self.ledger.append(run_id, "INTERVIEW_COMPLETED", {"suspect_id": args.suspect_id}, agent["id"])
            return {"evidence": items}
        if tool == "search_case_records":
            records = [e for e in self.case.search(args.query) if e["kind"] == "record"]
            return {"evidence": self._grant(run_id, agent, records, tool)}
        if tool == "inspect_timeline":
            return {"evidence": self._grant(run_id, agent, self.case.timeline(), tool)}
        if tool == "submit_finding":
            self._require_known(agent, args.evidence)
            fid = uuid.uuid4().hex
            with self.ledger.connect() as db:
                db.execute("INSERT INTO findings VALUES (?,?,?,?,?,?)", (fid, run_id, agent["id"], args.text,
                           canonical(args.evidence), utcnow()))
            self.ledger.append(run_id, "FINDING_CREATED", {"finding_id": fid, **args.model_dump()}, agent["id"])
            return {"finding_id": fid}
        if tool == "submit_hypothesis":
            if args.suspect_id not in self.case.suspects:
                raise PolicyError("Unknown suspect")
            self._require_known(agent, args.supporting_evidence + args.contradicting_evidence)
            with self.ledger.connect() as db:
                prior = db.execute("SELECT id FROM hypotheses WHERE run_id=? AND agent_id=? ORDER BY rowid DESC LIMIT 1",
                                   (run_id, agent["id"])).fetchone()
            hid = uuid.uuid4().hex
            event = self.ledger.append(run_id, "HYPOTHESIS_CHANGED" if prior else "HYPOTHESIS_CREATED",
                                       {"hypothesis_id": hid, "supersedes": prior["id"] if prior else None,
                                        **args.model_dump()}, agent["id"])
            with self.ledger.connect() as db:
                db.execute("INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (hid, run_id, agent["id"], args.suspect_id, args.claim, args.confidence,
                            canonical(args.supporting_evidence), canonical(args.contradicting_evidence),
                            args.reason_for_change, prior["id"] if prior else None, utcnow(), event["sequence"]))
            return {"hypothesis_id": hid, "supersedes": prior["id"] if prior else None}
        if tool == "challenge_hypothesis":
            self._require_known(agent, args.evidence)
            with self.ledger.connect() as db:
                target = db.execute("SELECT agent_id FROM hypotheses WHERE id=? AND run_id=?", (args.hypothesis_id, run_id)).fetchone()
            if not target:
                raise PolicyError("Unknown hypothesis in this run")
            return self._message(run_id, agent, MessageInput(recipient=target["agent_id"], type="challenge_agent",
                content=f"Challenge {args.hypothesis_id}: {args.reason}", related_evidence=args.evidence))
        if tool == "request_specialist":
            return self._specialist(run_id, agent, args)
        if tool == "create_investigation_task":
            return self._message(run_id, agent, MessageInput(recipient=args.recipient, type="task_handoff", content=args.task,
                                                             related_task=args.task))
        if tool in {"send_message", "request_peer_review", "share_finding"}:
            data = args.model_dump()
            if tool == "request_peer_review":
                data["type"] = "request_review"
            if tool == "share_finding":
                data["type"] = "share_finding"
            return self._message(run_id, agent, MessageInput.model_validate(data))
        if tool == "submit_final_accusation":
            if agent["parent_id"] is not None:
                raise PolicyError("Only leads submit final accusations")
            if args.suspect_id not in self.case.suspects or any(s not in self.case.suspects for s in args.alternatives):
                raise PolicyError("Unknown suspect")
            self._require_known(agent, args.supporting_evidence + args.contradicting_evidence)
            with self.ledger.connect() as db:
                received = {row["id"] for row in db.execute(
                    "SELECT id FROM messages WHERE run_id=? AND recipient=?", (run_id, agent["id"]))}
                if not set(args.influenced_by_messages) <= received:
                    raise PolicyError("Influence citation is not a received message")
                if db.execute("SELECT 1 FROM accusations WHERE run_id=? AND agent_id=? AND stage=?",
                              (run_id, agent["id"], stage)).fetchone():
                    raise PolicyError("Accusation already submitted")
                db.execute("INSERT INTO accusations VALUES (?,?,?,?,?)",
                           (run_id, agent["id"], stage, canonical(args.model_dump()), utcnow()))
            self.ledger.append(run_id, "FINAL_ACCUSATION", {"stage": stage, "report": args.model_dump()}, agent["id"])
            return {"stage": stage, "recorded": True}
        raise PolicyError("Unknown tool")

    def _message(self, run_id: str, agent: dict, args: MessageInput) -> dict:
        recipient = self._agent(run_id, args.recipient)
        if recipient["status"] != "active":
            raise PolicyError("Recipient is inactive")
        if recipient["id"] == agent["id"]:
            raise PolicyError("Cannot message self")
        self._require_known(agent, args.related_evidence)
        message_id = uuid.uuid4().hex
        with self.ledger.connect() as db:
            db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
                       (message_id, run_id, agent["id"], recipient["id"], args.type, args.content,
                        canonical(args.related_evidence), args.related_task, utcnow()))
        self.ledger.append(run_id, "MESSAGE_SENT", {"message_id": message_id, **args.model_dump()}, agent["id"])
        if args.related_evidence:
            self._grant(run_id, recipient, [self.case.get(eid) for eid in args.related_evidence], "message")
        self.ledger.append(run_id, "MESSAGE_RECEIVED", {"message_id": message_id, "sender": agent["id"]}, recipient["id"])
        return {"message_id": message_id, "delivered": True}

    def _specialist(self, run_id: str, agent: dict, args: SpecialistInput) -> dict:
        if agent["depth"] >= self.settings.max_depth - 1:
            raise PolicyError("Delegation depth limit")
        with self.ledger.connect() as db:
            total = db.execute("SELECT COUNT(*) AS n FROM agents WHERE run_id=?", (run_id,)).fetchone()["n"]
            workers = db.execute("SELECT COUNT(*) AS n FROM agents WHERE run_id=? AND lead_id=? AND parent_id IS NOT NULL",
                                 (run_id, agent["lead_id"])).fetchone()["n"]
            duplicate = db.execute("SELECT 1 FROM agents WHERE run_id=? AND parent_id=? AND role=?", (run_id, agent["id"],
                                   f"worker:{args.specialization}")).fetchone()
            if total >= self.settings.max_total_agents or workers >= self.settings.max_workers_per_lead:
                raise PolicyError("Agent creation limit")
            if duplicate:
                raise PolicyError("Duplicate worker specialization")
            worker_id = uuid.uuid4().hex
            db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (worker_id, run_id, agent["id"], agent["lead_id"], f"worker:{args.specialization}", args.task,
                        agent["depth"] + 1, "active", canonical({"known_evidence": []}), agent["model"], utcnow(), None, 0))
        self.ledger.append(run_id, "WORKER_REQUESTED", args.model_dump(), agent["id"])
        self.ledger.append(run_id, "WORKER_CREATED", {"worker_id": worker_id, "parent_id": agent["id"],
                                                       "specialization": args.specialization}, agent["id"])
        self.ledger.append(run_id, "AGENT_CREATED", {"role": f"worker:{args.specialization}", "task": args.task}, worker_id)
        return {"worker_id": worker_id}
