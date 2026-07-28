"""
The structured output contract with Gemini.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RootCauseAnalysis(BaseModel):
    summary: str = Field(
        description=(
            "Two to four sentences naming the most likely root cause of this entity's current state, "
            "referring to the specific entity ids, failure records, and metric movements in the context."
        )
    )
    next_steps: list[str] = Field(
        description=(
            "Between two and five concrete debugging or remediation actions an operator should take next, "
            "ordered most useful first. Each one a single imperative sentence."
        )
    )
