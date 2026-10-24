"""Pydantic v2 models for structured LLM output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Entities(BaseModel):
    entities: list[str]


class ImpactReport(BaseModel):
    affected_services: list[str]
    dependencies: list[str]
    complexity: Literal["Low", "Medium", "High"]
    risk: Literal["Low", "Medium", "High"]
    effort_days: float = Field(ge=0, le=999)
    testing_strategy: str


class InvestItem(BaseModel):
    pass_: bool = Field(alias="pass")
    reason: str = ""

    model_config = {"populate_by_name": True}


class StoryDraft(BaseModel):
    title: str
    description: str
    acceptance_criteria: list[str] = Field(min_length=1)
    invest_check: dict[str, InvestItem]

    @field_validator("invest_check")
    @classmethod
    def _six_letters(cls, v: dict[str, InvestItem]) -> dict[str, InvestItem]:
        missing = [k for k in "INVEST" if k not in v]
        if missing:
            raise ValueError(f"invest_check is missing: {missing}")
        return v


class CodeFile(BaseModel):
    path: str
    content: str


class CodeFiles(BaseModel):
    files: list[CodeFile] = Field(min_length=1)


class ScenarioDraft(BaseModel):
    title: str
    phase: Literal["SIT", "UAT", "REGRESSION"]
    test_type: Literal["FUNCTIONAL", "NEGATIVE", "BOUNDARY", "INTEGRATION"]
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    automated: bool
    steps: list[str]
    expected_result: str


class ScenarioList(BaseModel):
    scenarios: list[ScenarioDraft] = Field(min_length=1)
