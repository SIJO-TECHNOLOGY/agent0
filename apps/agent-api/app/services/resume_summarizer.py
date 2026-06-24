"""LLM-backed candidate resume summarization."""

from __future__ import annotations

import logging
import re

from app.services.llm_planner import ChatFn

logger = logging.getLogger(__name__)


class ResumeSummarizer:
    """Generate a concise recruiter-facing summary from parsed CV text."""

    def __init__(self, chat_fn: ChatFn) -> None:
        self._chat_fn = chat_fn

    async def summarize(
        self,
        *,
        candidate_name: str | None,
        title: str | None,
        resume_text: str,
    ) -> str | None:
        text = _compact_whitespace(resume_text)
        if len(text) < 120:
            return None

        system_prompt = (
            "Tu es un assistant RH. Tu synthétises un CV en français pour une "
            "fiche candidat. Réponds uniquement par le résumé final, sans puces, "
            "sans guillemets, sans titre."
        )
        user_prompt = (
            "Analyse le contenu du CV ci-dessous et rédige un résumé naturel, "
            "court et terminé par une phrase complète. "
            "Contraintes strictes: 1 phrase maximum, 180 à 230 caractères, "
            "ne pas inventer d'information, ne pas lister les coordonnées, "
            "ne pas mentionner le nom du candidat sauf si nécessaire.\n\n"
            f"Candidat: {candidate_name or 'Non renseigné'}\n"
            f"Intitulé connu: {title or 'Non renseigné'}\n\n"
            f"CV:\n{text[:6000]}"
        )
        try:
            raw = await self._chat_fn(system_prompt, user_prompt)
        except Exception:  # noqa: BLE001 - summary must not break search
            logger.exception("resume_summarizer.failed")
            return None
        return _clean_summary(raw)


def _clean_summary(value: str) -> str | None:
    text = _compact_whitespace(value).strip(" \"'“”«»")
    if not text:
        return None
    text = re.sub(r"^(résumé|resume)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = _keep_complete_sentence(text, limit=240)
    if len(text) < 40:
        return None
    return text


def _keep_complete_sentence(value: str, *, limit: int) -> str:
    text = _compact_whitespace(value)
    if len(text) <= limit and text[-1:] in ".!?":
        return text

    sentence_matches = list(re.finditer(r"[^.!?]+[.!?]", text))
    complete = ""
    for match in sentence_matches:
        candidate = (complete + " " + match.group(0).strip()).strip()
        if len(candidate) > limit:
            break
        complete = candidate
    if complete:
        return complete

    cut = text[:limit].rsplit(" ", 1)[0].strip(" ,;:-")
    if not cut:
        cut = text[:limit].strip(" ,;:-")
    return f"{cut}."


def _compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
