from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillDefinition(StrictModel):
    id: str
    name: str
    description: str
    tools: list[str]


SKILLS = {
    skill.id: skill
    for skill in [
        SkillDefinition(
            id="scene-analysis",
            name="Scene analysis",
            description="Inspect the scene and follow up on already discovered physical evidence.",
            tools=["inspect_crime_scene", "inspect_evidence"],
        ),
        SkillDefinition(
            id="forensics",
            name="Forensics",
            description="Request controlled laboratory analysis for discovered evidence.",
            tools=["inspect_evidence", "request_forensic_analysis"],
        ),
        SkillDefinition(
            id="interviews",
            name="Interviews",
            description="Interview suspects and compare their accounts.",
            tools=["interview_suspect"],
        ),
        SkillDefinition(
            id="records-research",
            name="Records research",
            description="Search the case record collection for relevant documents.",
            tools=["search_case_records", "inspect_evidence"],
        ),
        SkillDefinition(
            id="timeline-analysis",
            name="Timeline analysis",
            description="Inspect and reconcile chronological evidence.",
            tools=["inspect_timeline", "inspect_evidence"],
        ),
        SkillDefinition(
            id="teamwork",
            name="Teamwork",
            description="Share findings, ask for review, and challenge team hypotheses.",
            tools=[
                "send_message",
                "request_peer_review",
                "share_finding",
                "challenge_hypothesis",
                "create_investigation_task",
            ],
        ),
        SkillDefinition(
            id="delegation",
            name="Delegation",
            description="Create a bounded specialist worker for a focused task.",
            tools=["request_specialist"],
        ),
    ]
}

# Every lead needs these tools to complete the auditable investigation protocol.
CORE_TOOLS = {"submit_finding", "submit_hypothesis", "submit_final_accusation", "send_message"}
COMMUNICATION_TOOLS = {"send_message", "request_peer_review", "share_finding", "challenge_hypothesis"}


class AgentTemplate(StrictModel):
    id: str
    name: str
    description: str
    mission: str
    skills: list[str]


TEMPLATES = {
    template.id: template
    for template in [
        AgentTemplate(
            id="lead-detective",
            name="Lead Detective",
            description="Balanced investigator for broad evidence gathering and synthesis.",
            mission="Build a complete evidence-cited theory, test alternatives, and coordinate the team.",
            skills=list(SKILLS),
        ),
        AgentTemplate(
            id="forensic-analyst",
            name="Forensic Analyst",
            description="Prioritizes physical evidence, laboratory results, and causal mechanisms.",
            mission="Establish means and identity through physical and forensic evidence.",
            skills=["scene-analysis", "forensics", "timeline-analysis", "teamwork"],
        ),
        AgentTemplate(
            id="timeline-analyst",
            name="Timeline Analyst",
            description="Reconstructs opportunity windows and tests alibis against records.",
            mission="Reconstruct the sequence of events and identify the viable opportunity window.",
            skills=["timeline-analysis", "records-research", "interviews", "teamwork"],
        ),
        AgentTemplate(
            id="interview-specialist",
            name="Interview Specialist",
            description="Focuses on testimony, contradictions, motive, and behavioral evidence.",
            mission="Test statements, motives, and contradictions while sharing useful leads.",
            skills=["interviews", "records-research", "scene-analysis", "teamwork"],
        ),
        AgentTemplate(
            id="skeptical-reviewer",
            name="Skeptical Reviewer",
            description="Challenges the leading theory and searches for disconfirming evidence.",
            mission="Stress test the team's theory, surface contradictions, and compare alternatives.",
            skills=["records-research", "timeline-analysis", "interviews", "teamwork"],
        ),
    ]
}


ModelId = Annotated[str, Field(min_length=3, max_length=120)]


class AgentInput(StrictModel):
    template_id: str = Field(default="lead-detective", min_length=3, max_length=64)
    name: str | None = Field(default=None, min_length=2, max_length=60)
    mission: str | None = Field(default=None, min_length=10, max_length=500)
    model: ModelId | None = None
    skills: list[str] | None = Field(default=None, min_length=1, max_length=len(SKILLS))

    @field_validator("model")
    @classmethod
    def valid_model_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.:/~+-]+", value):
            raise ValueError("model contains unsupported characters")
        return value

    @field_validator("skills")
    @classmethod
    def valid_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(set(value)) != len(value):
            raise ValueError("skills must be unique")
        unknown = set(value) - set(SKILLS)
        if unknown:
            raise ValueError(f"unknown skills: {', '.join(sorted(unknown))}")
        return value

    @model_validator(mode="after")
    def valid_template(self) -> AgentInput:
        if self.template_id not in TEMPLATES:
            raise ValueError("unknown agent template")
        return self


def resolve_agent(agent: AgentInput, default_model: str) -> dict:
    template = TEMPLATES[agent.template_id]
    return {
        "template_id": template.id,
        "name": agent.name or template.name,
        "description": template.description,
        "mission": agent.mission or template.mission,
        "model": agent.model or default_model,
        "skills": agent.skills or template.skills,
    }


def default_team(count: int, default_model: str) -> list[dict]:
    template_ids = ["lead-detective", "forensic-analyst", "timeline-analyst"]
    return [resolve_agent(AgentInput(template_id=template_ids[index]), default_model) for index in range(count)]


def allowed_tools(skill_ids: list[str]) -> set[str]:
    tools = set(CORE_TOOLS)
    for skill_id in skill_ids:
        tools.update(SKILLS[skill_id].tools)
    return tools


def public_catalog() -> dict:
    return {
        "skills": [skill.model_dump() for skill in SKILLS.values()],
        "templates": [template.model_dump() for template in TEMPLATES.values()],
        "core_tools": sorted(CORE_TOOLS),
    }
