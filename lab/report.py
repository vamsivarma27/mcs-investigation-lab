from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from .case import CaseEngine
from .ledger import Ledger

PHASES = [
    ("INITIALIZING", "Setup"),
    ("INVESTIGATING", "Evidence gathering"),
    ("INDEPENDENT_CONCLUSIONS", "Independent conclusions"),
    ("DELIBERATION", "Team deliberation"),
    ("FINALIZED", "Final reports locked"),
    ("EVALUATING", "Evaluation"),
    ("COMPLETED", "Complete"),
]


def _duration(start: str, end: str | None) -> int | None:
    if not end:
        return None
    try:
        return max(0, round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    except ValueError:
        return None


def build_run_report(ledger: Ledger, case: CaseEngine, run_id: str) -> dict:
    with ledger.connect() as db:
        run_row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run_row:
            raise KeyError(run_id)
        agents = [dict(row) for row in db.execute(
            "SELECT * FROM agents WHERE run_id=? ORDER BY created_at,id", (run_id,)
        )]
        messages = [dict(row) for row in db.execute("SELECT * FROM messages WHERE run_id=?", (run_id,))]
        hypotheses = [dict(row) for row in db.execute(
            "SELECT * FROM hypotheses WHERE run_id=? ORDER BY event_sequence", (run_id,)
        )]
        accusations = [dict(row) for row in db.execute("SELECT * FROM accusations WHERE run_id=?", (run_id,))]
        evaluation_row = db.execute("SELECT result FROM evaluations WHERE run_id=?", (run_id,)).fetchone()
    run = dict(run_row)
    events = ledger.events(run_id)
    counts = Counter(event["event_type"] for event in events)
    evidence_ids = sorted({event["payload"].get("evidence_id") for event in events
                           if event["event_type"] == "EVIDENCE_ACCESSED" and event["payload"].get("evidence_id")})
    total_evidence = len(case.evidence)
    tool_usage = Counter(event["payload"].get("tool") for event in events
                         if event["event_type"] == "TOOL_REQUEST" and event["payload"].get("tool"))
    successful_tools = counts["TOOL_RESULT"]
    model_responses = [event for event in events if event["event_type"] in {"MODEL_RESPONSE", "JEV_DECISION"}]
    usage = {
        "model_calls": counts["MODEL_REQUEST"] + counts["JEV_REQUEST"],
        "input_tokens": sum(event["payload"].get("usage", {}).get("prompt_tokens",
                            event["payload"].get("usage", {}).get("input_tokens", 0)) for event in model_responses),
        "output_tokens": sum(event["payload"].get("usage", {}).get("completion_tokens",
                             event["payload"].get("usage", {}).get("output_tokens", 0)) for event in model_responses),
        "cost_usd": round(sum(event["payload"].get("cost") or 0 for event in model_responses), 6),
    }

    reached = {event["event_type"]: event for event in events}
    phase_rows = []
    current_index = next((i for i, (key, _) in enumerate(PHASES) if key == run["phase"]), -1)
    for index, (key, label) in enumerate(PHASES):
        event = reached.get(key)
        if event:
            status = "current" if key == run["phase"] else "complete"
        elif run["phase"] == "FAILED" and index == max(0, current_index):
            status = "failed"
        else:
            status = "pending"
        phase_rows.append({"key": key, "label": label, "status": status,
                           "sequence": event["sequence"] if event else None,
                           "timestamp": event["timestamp"] if event else None})
    if run["phase"] == "FAILED":
        completed_indexes = [i for i, (key, _) in enumerate(PHASES) if key in reached]
        failed_index = max(completed_indexes) if completed_indexes else 0
        phase_rows[failed_index]["status"] = "failed"

    agent_progress = []
    agent_names = {agent["id"]: agent["role"] for agent in agents}
    for agent in agents:
        aid = agent["id"]
        requests = [event for event in events if event["agent_id"] == aid and event["event_type"] == "TOOL_REQUEST"]
        agent_tools = Counter(event["payload"].get("tool") for event in requests)
        known = json.loads(agent["private_state"]).get("known_evidence", [])
        own_hypotheses = [item for item in hypotheses if item["agent_id"] == aid]
        own_messages = [item for item in messages if item["sender"] == aid]
        own_accusations = [item for item in accusations if item["agent_id"] == aid]
        dominant, repeated = agent_tools.most_common(1)[0] if agent_tools else (None, 0)
        display_status = "failed" if run["phase"] == "FAILED" and agent["status"] == "active" else agent["status"]
        agent_progress.append({
            "id": aid, "role": agent["role"], "status": display_status,
            "tool_calls": agent["tool_calls"], "tool_requests": len(requests),
            "unique_evidence": len(known), "evidence_ids": known,
            "hypotheses": len(own_hypotheses), "messages_sent": len(own_messages),
            "accusations": len(own_accusations), "dominant_tool": dominant,
            "dominant_tool_count": repeated,
            "last_action": requests[-1]["payload"].get("tool") if requests else None,
        })

    event_groups = {
        "Model decisions": counts["MODEL_RESPONSE"] + counts["JEV_DECISION"],
        "Tool activity": counts["TOOL_REQUEST"] + counts["TOOL_RESULT"],
        "Evidence discoveries": counts["EVIDENCE_ACCESSED"],
        "Communication": counts["MESSAGE_SENT"] + counts["MESSAGE_RECEIVED"],
        "Belief updates": counts["HYPOTHESIS_CREATED"] + counts["HYPOTHESIS_CHANGED"] + counts["FINAL_ACCUSATION"],
        "Errors and denials": counts["MODEL_ERROR"] + counts["TOOL_DENIED"] + counts["POLICY_DENIAL"] + counts["RUN_FAILED"],
    }

    message_types = Counter(message["type"] for message in messages)
    shared_evidence = sorted({eid for message in messages for eid in json.loads(message["related_evidence"])})
    mentioned_suspects = [suspect["name"] for suspect in case.data["suspects"]
                          if any(suspect["name"].lower() in message["content"].lower() for message in messages)]
    topic_tags = Counter(tag for eid in shared_evidence for tag in case.get(eid)["tags"])
    top_topics = [tag for tag, _ in topic_tags.most_common(5)]
    conversation = [{
        "id": message["id"], "sender": agent_names.get(message["sender"], message["sender"][:8]),
        "recipient": agent_names.get(message["recipient"], message["recipient"][:8]),
        "type": message["type"], "content": message["content"],
        "related_evidence": json.loads(message["related_evidence"]), "created_at": message["created_at"],
    } for message in messages]
    if messages:
        type_summary = ", ".join(
            f"{count} {kind.replace('_', ' ')}" for kind, count in message_types.most_common()
        )
        suspect_summary = ", ".join(mentioned_suspects[:3]) or "the leading suspects"
        topic_summary = ", ".join(top_topics) or "the available evidence"
        communication_overview = (
            f"The team exchanged {len(messages)} messages: {type_summary}. They focused on {suspect_summary} "
            f"and discussed {topic_summary}, referencing {len(shared_evidence)} unique evidence items."
        )
    else:
        communication_overview = "The agents did not communicate during this run."
    influence = []
    if evaluation_row:
        evaluation = json.loads(evaluation_row["result"])
        for item in evaluation.get("agents", []):
            before, final = item.get("independent"), item.get("final")
            influence.append({
                "role": item["role"], "changed_suspect": item.get("changed_after_deliberation", False),
                "before_suspect": before.get("suspect_id") if before else None,
                "final_suspect": final.get("suspect_id") if final else None,
                "confidence_change": item.get("confidence_change"),
                "declared_message_count": len(item.get("declared_influence_message_ids", [])),
            })

    if run["phase"] == "COMPLETED":
        headline = "Investigation completed"
        tone = "success"
        plain_summary = (f"The team completed all stages, surfaced {len(evidence_ids)} of {total_evidence} evidence items, "
                         f"and submitted {len(accusations)} accusation records. Evaluation results are available.")
    elif run["phase"] == "FAILED":
        headline = "Investigation stopped before completion"
        tone = "error"
        plain_summary = (f"The run stopped after {usage['model_calls']} model requests and {successful_tools} successful tool actions. "
                         f"Agents surfaced {len(evidence_ids)} of {total_evidence} evidence items, created {len(hypotheses)} hypotheses, "
                         f"and submitted {len(accusations)} accusation records.")
    else:
        headline = "Investigation in progress"
        tone = "active"
        plain_summary = (f"The team is currently in {run['phase'].replace('_', ' ').lower()} with "
                         f"{len(evidence_ids)} evidence items surfaced and {successful_tools} successful tool actions.")

    what_happened = [
        f"{len(agents)} investigators were created for this run.",
        f"They made {sum(tool_usage.values())} tool requests; {successful_tools} completed successfully.",
        f"They surfaced {len(evidence_ids)} unique evidence items and recorded {len(hypotheses)} hypotheses.",
        f"They exchanged {len(messages)} messages and submitted {len(accusations)} accusation records.",
    ]
    if run["phase"] == "FAILED" and run["error"]:
        what_happened.append(f"The run stopped because: {run['error']}")

    recommendations = []
    if run["phase"] == "FAILED":
        if not hypotheses:
            recommendations.append("Require each lead to record a hypothesis before the evidence gathering budget is exhausted.")
        if not messages:
            recommendations.append("Require at least one evidence sharing or peer review message before deliberation.")
        if not accusations:
            recommendations.append("Force the structured accusation tool when the run enters a conclusion stage.")
        if tool_usage and tool_usage.most_common(1)[0][1] > max(2, successful_tools // 2):
            recommendations.append("Block repeated identical reads and show each agent its recent action history.")
    elif run["phase"] == "COMPLETED":
        recommendations.append("Open Evaluation to review answer accuracy, explanation quality, and missed evidence.")

    notable_types = {"RUN_FAILED", "MODEL_ERROR", "TOOL_DENIED", "EVIDENCE_ACCESSED",
                     "HYPOTHESIS_CREATED", "HYPOTHESIS_CHANGED", "MESSAGE_SENT", "FINAL_ACCUSATION"}
    notable = [event for event in events if event["event_type"] in notable_types][-16:]
    integrity = ledger.verify(run_id)
    return {
        "run_id": run_id, "status": run["phase"], "tone": tone, "headline": headline,
        "plain_summary": plain_summary, "failure_reason": run["error"],
        "what_happened": what_happened, "recommended_actions": recommendations,
        "metrics": {
            "duration_seconds": _duration(run["created_at"], run["finished_at"]),
            "agents": len(agents), "evidence_found": len(evidence_ids), "evidence_total": total_evidence,
            "evidence_percent": round(100 * len(evidence_ids) / total_evidence) if total_evidence else 0,
            "tool_requests": sum(tool_usage.values()), "successful_tools": successful_tools,
            "model_errors": counts["MODEL_ERROR"], "messages": len(messages),
            "hypotheses": len(hypotheses), "accusations": len(accusations),
            "audit_events": len(events), "audit_valid": integrity["valid"], **usage,
        },
        "phases": phase_rows, "agent_progress": agent_progress,
        "communication_summary": {
            "overview": communication_overview,
            "message_count": len(messages), "shared_evidence": shared_evidence,
            "mentioned_suspects": mentioned_suspects, "topics": top_topics,
            "by_type": [{"label": kind.replace("_", " "), "value": count}
                        for kind, count in message_types.most_common()],
            "conversation": conversation, "influence": influence,
        },
        "charts": {
            "tool_usage": [{"label": name, "value": value} for name, value in tool_usage.most_common()],
            "event_groups": [{"label": name, "value": value} for name, value in event_groups.items()],
            "evidence_by_agent": [{"label": item["role"], "value": item["unique_evidence"]} for item in agent_progress],
        },
        "notable_events": notable,
    }
