"""Agent1 LLM reconciliation — the data-coherence judge.

When the deterministic normaliser flags a candidate as ambiguous (see
``normalizer.detect_conflicts``), this module asks an LLM to judge the
coherence of that candidate's data across experience, skills, languages, and
title, and to return a reconciled view.

Design:
  - **Grounded.** The LLM only reconciles/interprets the text we extracted
    (CV, technical document, title); it must not invent data.
  - **Bounded & cheap.** Only conflicting candidates are sent, batched into a
    single call per search; texts are truncated.
  - **Fail-safe.** Any LLM/parse/validation error leaves the deterministic
    result untouched (the caller keeps the original values).
  - **Confidence-gated.** A judgement only overrides the deterministic value
    when its ``confidence`` clears the configured threshold.

The LLM call itself is injected via ``ChatFn`` so production wires up a real
provider while tests pass a fake.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# (system_prompt, user_prompt) -> raw model text. Same shape as the planner's.
ChatFn = Callable[[str, str], Awaitable[str]]

# Keep token usage bounded: truncate each text field before sending.
_MAX_CV_CHARS: Final[int] = 4000
_MAX_TECHDOC_CHARS: Final[int] = 2000


@dataclass(frozen=True)
class ReconcileInput:
    """Everything the LLM needs to judge one candidate, fully grounded."""

    candidate_id: str
    title: str | None
    cv_text: str
    techdoc_text: str
    conflicts: list[str]
    # Deterministic values, so the LLM can confirm or correct them.
    det_experience_years: int | None
    det_skills: list[str] = field(default_factory=list)
    det_languages: list[str] = field(default_factory=list)


class Agent1Judgement(BaseModel):
    """LLM verdict on one candidate's reconciled data."""

    candidate_id: str
    experience_years: int | None = Field(default=None, ge=0, le=70)
    experience_label: str | None = None
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    title: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = ""


class Agent1ReconcilerError(RuntimeError):
    """Raised internally on parse/validation failure; never escapes reconcile()."""


_SYSTEM_PROMPT: Final[str] = (
    "You are a data-quality judge for recruitment profiles. For each candidate "
    "you receive raw text extracted from their CV and technical document, plus "
    "the values a deterministic parser produced and the conflicts it detected. "
    "Your job is to decide the most coherent value for each field, using ONLY "
    "the provided text. Rules:\n"
    "- experience_years: the candidate's real YEARS OF PROFESSIONAL EXPERIENCE. "
    "Never confuse it with their AGE, a project duration, or years of data. If "
    "the text states it explicitly, use that. If only an experience band is "
    "implied, leave experience_years null and put the band in experience_label.\n"
    "- skills / languages: keep only items genuinely supported by the text.\n"
    "- title: the candidate's job title, cleaned up.\n"
    "- Never invent data not present in the text. If unsure, return null/empty "
    "and a low confidence.\n"
    "- confidence: 0..1, how sure you are of this reconciliation.\n"
    "Return ONLY a JSON object: {\"judgements\": [ {candidate_id, "
    "experience_years, experience_label, skills, languages, title, confidence, "
    "notes}, ... ]}. No prose, no markdown fences."
)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " […]"


def build_user_prompt(inputs: list[ReconcileInput]) -> str:
    payload = {
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "title": c.title,
                "detected_conflicts": c.conflicts,
                "deterministic": {
                    "experience_years": c.det_experience_years,
                    "skills": c.det_skills,
                    "languages": c.det_languages,
                },
                "cv_text": _truncate(c.cv_text, _MAX_CV_CHARS),
                "technical_document_text": _truncate(c.techdoc_text, _MAX_TECHDOC_CHARS),
            }
            for c in inputs
        ]
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_judgements(raw_text: str) -> dict[str, Agent1Judgement]:
    """Parse the LLM response into a {candidate_id: Agent1Judgement} map.

    Tolerant of a single Markdown code fence. Raises Agent1ReconcilerError on
    any structural failure; individual malformed judgements are skipped.
    """
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    stripped = stripped.strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise Agent1ReconcilerError(f"non-JSON output: {exc}") from exc
    if not isinstance(payload, dict):
        raise Agent1ReconcilerError("top-level JSON must be an object")

    raw_list = payload.get("judgements")
    if not isinstance(raw_list, list):
        raise Agent1ReconcilerError("missing 'judgements' array")

    out: dict[str, Agent1Judgement] = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        try:
            judgement = Agent1Judgement.model_validate(item)
        except ValidationError:
            logger.warning("agent1.reconcile.bad_judgement", extra={"item": item})
            continue
        out[judgement.candidate_id] = judgement
    return out


class Agent1Reconciler:
    """Calls the LLM to reconcile ambiguous candidates' data."""

    def __init__(
        self,
        chat_fn: ChatFn,
        *,
        confidence_threshold: float = 0.6,
        max_candidates: int = 10,
    ) -> None:
        self._chat_fn = chat_fn
        self._threshold = confidence_threshold
        self._max_candidates = max_candidates

    @property
    def confidence_threshold(self) -> float:
        return self._threshold

    async def reconcile(
        self, inputs: list[ReconcileInput]
    ) -> dict[str, Agent1Judgement]:
        """Return high-confidence judgements keyed by candidate id.

        Never raises: on any failure it returns an empty dict so the caller
        keeps the deterministic result.
        """
        if not inputs:
            return {}
        batch = inputs[: self._max_candidates]
        try:
            user = build_user_prompt(batch)
            raw = await self._chat_fn(_SYSTEM_PROMPT, user)
            judged = parse_judgements(raw)
        except Agent1ReconcilerError as exc:
            logger.warning("agent1.reconcile.parse_failed", extra={"error": str(exc)})
            return {}
        except Exception:  # noqa: BLE001 — reconciliation must never break the search
            logger.exception("agent1.reconcile.failed")
            return {}

        # Keep only confident judgements for candidates we actually asked about.
        asked = {c.candidate_id for c in batch}
        confident = {
            cid: j
            for cid, j in judged.items()
            if cid in asked and j.confidence >= self._threshold
        }
        logger.info(
            "agent1.reconcile.done",
            extra={
                "asked": len(batch),
                "returned": len(judged),
                "applied": len(confident),
            },
        )
        return confident
