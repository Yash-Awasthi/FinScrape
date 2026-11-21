"""The schema a model reply has to satisfy, and the repair prompt when it does not.

`call_ai` used to accept whatever JSON came back and patch it up afterwards, so a reply that
was missing fields, or was not JSON at all, quietly became a heuristic-shaped verdict. This
module is the boundary: `reply_errors` says what is wrong in one line per problem, and
`repair_prompt` quotes those lines back to the model once.

The checks are structural on purpose — types and ranges. Enum membership (`event_type`,
`impact_direction`, …) is normalised later by `ai_client._validate_response`, because a model
writing `"OTHER"` is a spelling to fix, not a reason to spend another API call.

    errors = reply_errors(data)          # [] when the reply is usable
    prompt = repair_prompt(prompt, raw_text, errors)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from finscrape.analysis.constants import VALID_EVENT_TYPES, VALID_IMPACT_DIRECTIONS

# Longest slice of an offending reply that is ever logged or quoted. A model reply is
# article-derived text; it is echoed back only to fix it, never stored.
SAMPLE_CHARS = 400

# Fields the pipeline reads without a `.get(..., default)` guard.
REQUIRED = ("relevant",)


class ModelReply(BaseModel):
    """One analysis reply. Unknown fields are kept: prompts evolve faster than schemas."""

    model_config = ConfigDict(extra="allow")

    relevant: bool
    event_type: str = "other"
    impact_direction: str = "neutral"
    signal_score: int = Field(default=0, ge=-5, le=5)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    subject: str = ""
    reasoning: str = ""
    magnitude: str = "medium"
    novelty: str = "standard"
    actionability: str = "medium"
    tickers: list[str] = Field(default_factory=list)
    affected_entities: list[dict[str, Any]] = Field(default_factory=list)
    second_order_effects: list[Any] = Field(default_factory=list)
    sector_impact: str = ""
    key_metrics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("signal_score", mode="before")
    @classmethod
    def _score(cls, value: Any) -> Any:
        # Qwen returns null and "3" where a number belongs. A blank score is a default, not
        # a reason to spend an API call on a repair.
        if value is None or value == "":
            return 0
        if isinstance(value, str):
            try:
                return int(float(value))
            except ValueError:
                return 0
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> Any:
        if value is None or value == "":
            return 0.5
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.5
        return value

    @field_validator("tickers", mode="before")
    @classmethod
    def _tickers(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("affected_entities", "second_order_effects", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("key_metrics", mode="before")
    @classmethod
    def _dict(cls, value: Any) -> Any:
        return {} if value is None else value


def reply_errors(data: Any) -> list[str]:
    """One line per schema problem; an empty list means the reply is usable."""
    if not isinstance(data, dict):
        return [f"reply is {type(data).__name__}, not a JSON object"]
    try:
        ModelReply.model_validate(data)
    except ValidationError as exc:
        return [
            f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        ]
    return []


def redacted_sample(raw: Any) -> str:
    """A short, single-line echo of a bad reply for logs — enough to debug, not an article."""
    text = raw if isinstance(raw, str) else repr(raw)
    collapsed = " ".join(str(text).split())
    return collapsed[:SAMPLE_CHARS] + ("…" if len(collapsed) > SAMPLE_CHARS else "")


def repair_prompt(prompt: str, sample: str, errors: list[str]) -> str:
    """The original prompt plus the reasons the last reply could not be used."""
    problems = "\n".join(f"- {error}" for error in errors) or "- the reply was not valid JSON"
    return (
        f"{prompt}\n\n"
        "---\n"
        "Your previous reply could not be used:\n"
        f"{problems}\n\n"
        f"Previous reply:\n{sample}\n\n"
        "Reply again with ONLY the corrected JSON object, no prose and no code fence."
    )


def describe_enums() -> str:
    """The allowed values, for prompt builders and error messages."""
    return (
        f"event_type one of {sorted(VALID_EVENT_TYPES)}; "
        f"impact_direction one of {sorted(VALID_IMPACT_DIRECTIONS)}"
    )
