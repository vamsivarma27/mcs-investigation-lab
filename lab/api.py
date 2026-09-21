from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Settings
from .orchestrator import Orchestrator
from .report import build_run_report

settings = Settings()
lab = Orchestrator(settings)
app = FastAPI(title="MCS Investigation Lab", version="0.3.0", docs_url="/api/docs", redoc_url=None)
STATIC = Path(__file__).parent / "static"


class NewRun(BaseModel):
    lead_count: int = Field(default=3, ge=2, le=3)
    case_id: str = Field(default="meridian-archive", min_length=3, max_length=100)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/app.css")
def css():
    return FileResponse(STATIC / "app.css", media_type="text/css")


@app.get("/app.js")
def js():
    return FileResponse(STATIC / "app.js", media_type="text/javascript")


@app.get("/api/health")
def health():
    return {"ok": True, "provider": settings.provider, "key_configured": bool(settings.api_key)}


@app.get("/api/case")
def case():
    return lab.case.overview()


@app.get("/api/cases")
def cases():
    return lab.catalog.list()


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str):
    try:
        return lab.catalog.get(case_id).overview()
    except KeyError:
        raise HTTPException(404, "Case not found") from None


@app.get("/api/runs")
def runs():
    with lab.ledger.connect() as db:
        rows = db.execute("SELECT id,phase,created_at,finished_at,config,error FROM runs ORDER BY created_at DESC LIMIT 50").fetchall()
    output = []
    for row in rows:
        config = json.loads(row["config"])
        output.append({**dict(row), "config": config,
                       "case_title": config.get("case_title", "The Meridian Archive"),
                       "case_difficulty": config.get("case_difficulty", "Moderate")})
    return output


@app.post("/api/runs", status_code=202)
def create_run(request: NewRun):
    try:
        return {"run_id": lab.start(request.lead_count, request.case_id)}
    except KeyError:
        raise HTTPException(404, "Case not found") from None


@app.get("/api/runs/{run_id}")
def snapshot(run_id: str):
    try:
        return lab.snapshot(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None


@app.get("/api/runs/{run_id}/events")
def events(run_id: str):
    try:
        lab.snapshot(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    return lab.ledger.events(run_id)


@app.get("/api/runs/{run_id}/integrity")
def integrity(run_id: str):
    try:
        lab.snapshot(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    return lab.ledger.verify(run_id)


@app.get("/api/runs/{run_id}/report")
def report(run_id: str):
    try:
        return build_run_report(lab.ledger, lab.case_for_run(run_id), run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None


@app.get("/api/compare")
def compare():
    with lab.ledger.connect() as db:
        rows = db.execute("SELECT r.id,r.phase,r.created_at,r.config,e.result FROM runs r LEFT JOIN evaluations e ON e.run_id=r.id ORDER BY r.created_at DESC LIMIT 50").fetchall()
    output = []
    for row in rows:
        config = json.loads(row["config"])
        result = json.loads(row["result"]) if row["result"] else None
        output.append({"run_id": row["id"], "phase": row["phase"], "created_at": row["created_at"],
                       "case_hash": config["case_hash"], "investigator_model": config["investigator_model"],
                       "case_title": config.get("case_title", "The Meridian Archive"),
                       "case_difficulty": config.get("case_difficulty", "Moderate"),
                       "decision_model": config["decision_model"],
                       "team": result["team"] if result else None,
                       "average_quality": round(sum(a["quality_score"] for a in result["agents"]) / len(result["agents"]), 1)
                       if result and result["agents"] else None})
    return output


@app.get("/api/runs/{run_id}/evidence")
def discovered_evidence(run_id: str):
    try:
        case = lab.case_for_run(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    ids = {event["payload"]["evidence_id"] for event in lab.ledger.events(run_id)
           if event["event_type"] == "EVIDENCE_ACCESSED"}
    return {eid: case.get(eid) for eid in sorted(ids)}


@app.get("/api/runs/{run_id}/graph")
def graph(run_id: str):
    from .graph import build_graph

    try:
        lab.snapshot(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    return build_graph(lab.ledger, run_id)
