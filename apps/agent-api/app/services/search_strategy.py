"""Generic, deterministic recall-first search strategy for ``searchCandidates``.

Pure functions only — no MCP/network/dictionary I/O. The Agent API
executor resolves dictionary ids and runs these passes; this module just
decides *structure*:

- derive search anchors (skills / role / domains) from the interpreted
  intent, generically (no hardcoded skill names), and
- build a bounded relaxation ladder of ``searchCandidates`` input dicts
  that starts focused and progressively broadens.

``searchCandidates`` is a recall tool: ``keywords`` supports only
``+term`` / ``"phrase"`` (NO boolean ``OR``/parentheses), and id filters
(``experiences``/``tools``) are exact and AND-ish. So we never cram every
criterion into one call and never emit boolean keyword syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# Boolean operators / grouping that BoondManager keyword search does NOT
# support — stripped so a planner-suggested term can't silently match
# nothing.
_BOOLEAN_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:and|or|not)\b", re.IGNORECASE
)
_DROP_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[()\"]")
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

# Best-effort role detection (LLM-declared `role` is preferred; this is a
# thin fallback). Substring match keeps it language-tolerant-ish.
_ROLE_SUFFIXES: Final[tuple[str, ...]] = (
    "developer",
    "engineer",
    "analyst",
    "manager",
    "architect",
    "consultant",
    "lead",
    "designer",
    "scientist",
    "administrator",
    "specialist",
    "devops",
    "tester",
    "developpeur",
    "ingenieur",
)
_ROLE_CONSTRAINT_KEYS: Final[tuple[str, ...]] = ("role", "title", "job_title")
_DOMAIN_CONSTRAINT_KEYS: Final[tuple[str, ...]] = (
    "domain",
    "last_experience_company",
    "company",
    "sector",
    "business_context",
)

# Real searchCandidates field names (live schema first).
KEYWORDS_FIELD: Final[str] = "keywords"
KEYWORDS_TYPE_FIELD: Final[str] = "keywordsType"
TOOLS_FIELD: Final[str] = "tools"
EXPERIENCE_FIELDS: Final[tuple[str, ...]] = (
    "experiences",
    "experience",
    "experienceLevel",
    "experience_id",
)
PAGE_FIELD: Final[str] = "page"
SIZE_FIELDS: Final[tuple[str, ...]] = ("maxResults", "numberPerPage")
_DEFAULT_SIZE: Final[int] = 25


@dataclass(frozen=True)
class Anchors:
    """Ordered, typed recall anchors derived from the interpreted intent."""

    skills: tuple[str, ...]
    role: str | None
    domains: tuple[str, ...]

    @property
    def primary(self) -> str | None:
        """The single strongest anchor for the first recall pass."""
        if self.skills:
            return self.skills[0]
        if self.role:
            return self.role
        if self.domains:
            return self.domains[0]
        return None

    def is_empty(self) -> bool:
        return not (self.skills or self.role or self.domains)


@dataclass(frozen=True)
class SearchPass:
    """One searchCandidates attempt in the relaxation ladder."""

    label: str
    inputs: dict[str, object]
    relaxed: bool


def safe_keywords(term: str) -> str:
    """Reduce a term to BoondManager-safe keyword text (no boolean syntax)."""
    cleaned = _DROP_CHARS_RE.sub(" ", term)
    cleaned = _BOOLEAN_TOKEN_RE.sub(" ", cleaned)
    return _WS_RE.sub(" ", cleaned).strip()


def _looks_like_role(entity: str) -> bool:
    low = entity.lower()
    return any(suffix in low for suffix in _ROLE_SUFFIXES)


def classify_anchors(
    entities: list[object],
    constraints: dict[str, str],
    skill_labels: set[str],
) -> Anchors:
    """Classify intent entities/constraints into skill / role / domain anchors.

    ``skill_labels`` is the set of lower-cased ``setting.tool`` dictionary
    labels; entities matching one are treated as concrete (server-side
    filterable) skills. Everything else stays a free-text recall anchor.
    No skill/role/domain value is hardcoded.
    """
    ents = [str(e).strip() for e in entities if str(e).strip()]
    skill_set = {label.strip().lower() for label in skill_labels if label.strip()}

    skills = tuple(e for e in ents if e.lower() in skill_set)

    role: str | None = None
    for key in _ROLE_CONSTRAINT_KEYS:
        value = constraints.get(key)
        if isinstance(value, str) and value.strip():
            role = value.strip()
            break
    if role is None:
        role = next(
            (e for e in ents if e not in skills and _looks_like_role(e)), None
        )

    domains: list[str] = []
    for key in _DOMAIN_CONSTRAINT_KEYS:
        value = constraints.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in domains:
            domains.append(value.strip())
    for entity in ents:
        if entity in skills or entity == role or entity in domains:
            continue
        domains.append(entity)

    return Anchors(skills=skills, role=role, domains=tuple(domains))


def _size_field(fields: set[str]) -> str | None:
    return next((f for f in SIZE_FIELDS if f in fields), None)


def _pagination(fields: set[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    if PAGE_FIELD in fields:
        out[PAGE_FIELD] = 1
    size = _size_field(fields)
    if size is not None:
        out[size] = _DEFAULT_SIZE
    return out


def _keyword_inputs(
    term: str, fields: set[str], *, keywords_type: str | None
) -> dict[str, object] | None:
    if KEYWORDS_FIELD not in fields:
        return None
    keywords = safe_keywords(term)
    if not keywords:
        return None
    inputs: dict[str, object] = _pagination(fields)
    inputs[KEYWORDS_FIELD] = keywords
    if keywords_type is not None and KEYWORDS_TYPE_FIELD in fields:
        inputs[KEYWORDS_TYPE_FIELD] = keywords_type
    return inputs


def _signature(inputs: dict[str, object]) -> tuple[tuple[str, str], ...]:
    """Identity of a pass ignoring pagination, for de-duplication."""
    ignore = {PAGE_FIELD, *SIZE_FIELDS}
    return tuple(
        sorted(
            (k, str(v)) for k, v in inputs.items() if k not in ignore
        )
    )


def build_recall_passes(
    anchors: Anchors,
    *,
    schema_fields: set[str],
    max_passes: int = 5,
) -> list[SearchPass]:
    """Build a bounded, de-duplicated, KEYWORD-ONLY recall ladder.

    ``searchCandidates`` is a recall tool and its exact-id ``tools`` filter
    is unreliable (it can kill recall), so the ladder never uses structured
    id filters as a hard constraint — precision comes later from evidence
    pre-ranking, enrichment, and ranking. Each pass carries a single
    high-signal keyword; pagination is added when the schema supports it.
    """
    fields = set(schema_fields)
    passes: list[SearchPass] = []
    seen: set[tuple[tuple[str, str], ...]] = set()

    def add(label: str, inputs: dict[str, object] | None, *, relaxed: bool) -> None:
        if inputs is None or KEYWORDS_FIELD not in inputs:
            return
        sig = _signature(inputs)
        if sig in seen:
            return
        seen.add(sig)
        passes.append(SearchPass(label=label, inputs=inputs, relaxed=relaxed))

    primary = anchors.primary

    # Pass 1 — strongest anchor as plain keywords (broad enough for recall).
    if primary is not None:
        add(
            "primary",
            _keyword_inputs(primary, fields, keywords_type="resumeTd"),
            relaxed=False,
        )

    # Pass 2 — role/title.
    if anchors.role:
        add(
            "role-titleSkills",
            _keyword_inputs(anchors.role, fields, keywords_type="titleSkills"),
            relaxed=True,
        )
        add(
            "role-title",
            _keyword_inputs(anchors.role, fields, keywords_type="title"),
            relaxed=True,
        )

    # Pass 3 — domain / business context separately.
    for domain in anchors.domains:
        add(
            "domain",
            _keyword_inputs(domain, fields, keywords_type="resumeTd"),
            relaxed=True,
        )

    # Pass 4 — remaining skills individually.
    for skill in anchors.skills[1:]:
        add(
            "skill",
            _keyword_inputs(skill, fields, keywords_type="resumeTd"),
            relaxed=True,
        )

    return passes[:max_passes]


# ---------------------------------------------------------------------------
# Evidence scoring — shared by summary pre-ranking and post-enrichment ranking
# ---------------------------------------------------------------------------

_YEARS_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:years?|yrs?|ans?)", re.IGNORECASE
)


def parse_years(text: str) -> int | None:
    """Largest explicit years-of-experience figure mentioned in free text."""
    best: int | None = None
    for match in _YEARS_RE.finditer(text):
        try:
            value = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if best is None or value > best:
            best = value
    return best


@dataclass(frozen=True)
class EvidenceWeights:
    """Relative importance of each criterion dimension."""

    skill: float = 0.4
    domain: float = 0.3
    seniority: float = 0.3
    role: float = 0.2


_WEIGHTS = EvidenceWeights()

_TOKEN_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[^0-9a-zA-Z]+")
# Grammatical words only — never domain vocabulary (so "banking"/"finance"
# stay matchable for "in banking" / "in finance" queries).
_DOMAIN_STOPWORDS: Final[frozenset[str]] = frozenset(
    {"and", "or", "the", "for", "with", "des", "les", "und", "the"}
)
_DOMAIN_MIN_TOKEN_LEN: Final[int] = 3


def domain_match_tokens(domains: tuple[str, ...] | list[str]) -> set[str]:
    """Generic match tokens for ambiguous business-domain terms.

    A user domain term may be an acronym, an expansion, or both (e.g.
    ``"cib (corporate & investment banking)"``). We split into tokens and
    keep each distinctive one (length ≥ 3, not a grammatical stopword), so
    the original acronym is preserved as a substring signal — ``"cib"``
    matches ``"SGCIB"`` — AND its expansion words still match. No domain
    value is hardcoded, so this works for banking, payments, finance,
    insurance, or any acronym a user supplies.
    """
    tokens: set[str] = set()
    for term in domains:
        if not isinstance(term, str):
            continue
        for raw in _TOKEN_SPLIT_RE.split(term.lower()):
            if len(raw) >= _DOMAIN_MIN_TOKEN_LEN and raw not in _DOMAIN_STOPWORDS:
                tokens.add(raw)
    return tokens


def evidence_score(
    haystack: str,
    *,
    skills: tuple[str, ...] | list[str],
    domains: tuple[str, ...] | list[str],
    role: str | None,
    candidate_min_years: int | None,
    required_min_years: int | None,
    weights: EvidenceWeights = _WEIGHTS,
) -> tuple[float, set[str]]:
    """Weighted multi-criteria evidence score in ``[0, 1]`` plus matched keys.

    Only criteria the query actually expressed contribute, so the score is
    the weighted fraction of *requested* criteria evidenced. Seniority
    counts only when the candidate's known experience meets the required
    minimum (unknown or below earns nothing — so a 3-year profile cannot
    tie a 10+-year one for a "10+ years" query). The returned key set
    (e.g. ``{"skill:java", "domain", "seniority"}``) lets callers report
    which criteria were never evidenced on any candidate.
    """
    hay = haystack.lower()
    dims: list[tuple[float, float]] = []
    hits: set[str] = set()

    norm_skills = [s.lower() for s in skills if s and s.strip()]
    if norm_skills:
        found = [s for s in norm_skills if s in hay]
        for skill in found:
            hits.add(f"skill:{skill}")
        dims.append((weights.skill, len(found) / len(norm_skills)))

    norm_domains = [d for d in domains if d and d.strip()]
    if norm_domains:
        # Match ANY distinctive token of the (possibly verbose/ambiguous)
        # domain term — so "cib (corporate & investment banking)" is
        # evidenced by "SGCIB", "corporate", "investment", or "banking".
        tokens = domain_match_tokens(norm_domains)
        domain_found = any(token in hay for token in tokens)
        if domain_found:
            hits.add("domain")
        dims.append((weights.domain, 1.0 if domain_found else 0.0))

    if role and role.strip():
        low = role.lower()
        role_found = low in hay or all(tok in hay for tok in low.split())
        if role_found:
            hits.add("role")
        dims.append((weights.role, 1.0 if role_found else 0.0))

    if required_min_years is not None:
        meets = (
            candidate_min_years is not None
            and candidate_min_years >= required_min_years
        )
        if meets:
            hits.add("seniority")
        dims.append((weights.seniority, 1.0 if meets else 0.0))

    if not dims:
        return 0.0, hits
    total_weight = sum(weight for weight, _ in dims)
    score = sum(weight * hit for weight, hit in dims) / total_weight
    return score, hits
