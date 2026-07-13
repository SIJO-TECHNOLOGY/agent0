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

from app.graph.intent_keywords import SKILL_ALIASES, LANG_NORMALIZATIONS

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
_DEFAULT_SIZE: Final[int] = 40


@dataclass(frozen=True)
class Anchors:
    """Ordered, typed recall anchors derived from the interpreted intent."""

    skills: tuple[str, ...]
    role: str | None
    domains: tuple[str, ...]
    name: str | None = None

    @property
    def primary(self) -> str | None:
        """The single strongest anchor for the first recall pass.

        Note: a person ``name`` is searched by its own dedicated first pass in
        ``build_recall_passes`` (it is the strongest possible anchor), so it is
        intentionally NOT folded into ``primary`` — that keeps the skill/role/
        domain ladder ordering identical for non-name queries.
        """
        if self.skills:
            return self.skills[0]
        if self.role:
            return self.role
        if self.domains:
            return self.domains[0]
        return None

    def is_empty(self) -> bool:
        return not (self.skills or self.role or self.domains or self.name)


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


_NAME_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]+", re.UNICODE)


def _name_token_set(text: str) -> set[str]:
    return {tok.lower() for tok in _NAME_WORD_RE.findall(text or "")}


def name_match_score(requested: str, candidate: str | None) -> float:
    """Fraction of the requested name's tokens present in a candidate's name.

    Token-set recall, case/accent-insensitive on case. An exact name (all
    requested tokens present) scores 1.0; a single shared surname scores
    proportionally less. Used to make a requested person the primary ranking
    signal — see ``rank_candidates``.
    """
    requested_tokens = _name_token_set(requested)
    if not requested_tokens:
        return 0.0
    candidate_tokens = _name_token_set(candidate or "")
    if not candidate_tokens:
        return 0.0
    matched = sum(1 for tok in requested_tokens if tok in candidate_tokens)
    return matched / len(requested_tokens)


def _looks_like_role(entity: str) -> bool:
    low = entity.lower()
    return any(suffix in low for suffix in _ROLE_SUFFIXES)


def classify_anchors(
    entities: list[object],
    constraints: dict[str, str],
    skill_labels: set[str],
    *,
    name: str | None = None,
) -> Anchors:
    """Classify intent entities/constraints into skill / role / domain anchors.

    ``skill_labels`` is the set of lower-cased ``setting.tool`` dictionary
    labels; entities matching one are treated as concrete (server-side
    filterable) skills. Everything else stays a free-text recall anchor.
    No skill/role/domain value is hardcoded.

    ``name`` is an optional person name (from ``constraints.name``). It is kept
    separate from skills/role/domains so it never pollutes domain ranking; the
    ladder searches it first via a dedicated pass.
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

    clean_name = name.strip() if isinstance(name, str) and name.strip() else None
    return Anchors(skills=skills, role=role, domains=tuple(domains), name=clean_name)


def _size_field(fields: set[str]) -> str | None:
    return next((f for f in SIZE_FIELDS if f in fields), None)


def _pagination(fields: set[str], page: int = 1) -> dict[str, object]:
    out: dict[str, object] = {}
    if PAGE_FIELD in fields:
        out[PAGE_FIELD] = page
    size = _size_field(fields)
    if size is not None:
        out[size] = _DEFAULT_SIZE
    return out


def _keyword_inputs(
    term: str, fields: set[str], *, keywords_type: str | None, page: int = 1
) -> dict[str, object] | None:
    if KEYWORDS_FIELD not in fields:
        return None
    keywords = safe_keywords(term)
    if not keywords:
        return None
    inputs: dict[str, object] = _pagination(fields, page)
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
    page: int = 1,
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

    # Pass 0 — a named person is the strongest possible anchor, so search the
    # name FIRST (not relaxed). The default full-text type (`resumeTd`) is what
    # actually surfaces a named candidate in BoondManager — `fullName` is
    # unreliable on this data. If this pass returns candidates the ladder stops
    # here; otherwise the skill/role/domain passes below act as a labeled
    # relaxation.
    if anchors.name:
        add(
            "name",
            _keyword_inputs(anchors.name, fields, keywords_type="resumeTd", page=page),
            relaxed=False,
        )

    # Pass 0b — COMBINED content anchors (skills + domains/company) as ONE
    # keyword query. BoondManager unions the terms and ranks by relevance, so a
    # candidate matching the most discriminating terms (e.g. a company + a skill,
    # "amundi java") surfaces at the top — far better recall than searching the
    # generic skill alone. Role/seniority words are deliberately EXCLUDED here:
    # in a full-text union they are noisy ("tech lead" pulls unrelated infra
    # profiles). The role still drives the title pass below and the ranking.
    content_terms: list[str] = []
    for term in (*anchors.domains, *anchors.skills):
        if term and term not in content_terms:
            content_terms.append(term)
    if len(content_terms) >= 2:
        add(
            "combined",
            _keyword_inputs(" ".join(content_terms), fields, keywords_type="resumeTd", page=page),
            relaxed=False,
        )

    # Pass 1 — strongest anchor as plain keywords (broad enough for recall).
    if primary is not None:
        add(
            "primary",
            _keyword_inputs(primary, fields, keywords_type="resumeTd", page=page),
            relaxed=False,
        )

    # Pass 2 — role/title.
    if anchors.role:
        add(
            "role-titleSkills",
            _keyword_inputs(anchors.role, fields, keywords_type="titleSkills", page=page),
            relaxed=True,
        )
        add(
            "role-title",
            _keyword_inputs(anchors.role, fields, keywords_type="title", page=page),
            relaxed=True,
        )

    # Pass 3 — domain / business context separately.
    for domain in anchors.domains:
        add(
            "domain",
            _keyword_inputs(domain, fields, keywords_type="resumeTd", page=page),
            relaxed=True,
        )

    # Pass 4 — remaining skills individually.
    for skill in anchors.skills[1:]:
        add(
            "skill",
            _keyword_inputs(skill, fields, keywords_type="resumeTd", page=page),
            relaxed=True,
        )

    return passes[:max_passes]


# ---------------------------------------------------------------------------
# Evidence scoring — shared by summary pre-ranking and post-enrichment ranking
# ---------------------------------------------------------------------------

_YEARS_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:years?|yrs?|ans?)", re.IGNORECASE
)

# Maps title-level seniority keywords to their approximate minimum years
# equivalent.  Used when explicit years data is absent — a "Lead" title
# implies ≥ 7 years of experience without any number in the profile.
_TITLE_SENIORITY_YEARS: Final[dict[str, int]] = {
    "junior": 1,
    "stagiaire": 1,
    "intern": 1,
    "mid": 3,
    "intermediate": 3,
    "confirmed": 3,
    "confirmé": 3,
    "confirme": 3,
    "senior": 5,
    "experienced": 5,
    "expérimenté": 5,
    "experimente": 5,
    "lead": 7,
    "staff": 7,
    "principal": 9,
    "architect": 8,
    "architecte": 8,
    "expert": 8,
    "director": 10,
    "directeur": 10,
    "vp": 12,
    "cto": 12,
    "cio": 12,
}

_TITLE_SENIORITY_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _TITLE_SENIORITY_YEARS) + r")\b",
    re.IGNORECASE,
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


def infer_years_from_title(title_haystack: str) -> int | None:
    """Estimate minimum years of experience from seniority keywords in a title.

    Returns the HIGHEST implied minimum found so a ``"Senior Lead Architect"``
    yields 8 (architect) rather than 5 (senior).  Returns ``None`` when no
    seniority keyword is found, so callers can distinguish "unknown" from 0.
    """
    best: int | None = None
    for match in _TITLE_SENIORITY_RE.finditer(title_haystack.lower()):
        years = _TITLE_SENIORITY_YEARS.get(match.group(1).lower())
        if years is not None and (best is None or years > best):
            best = years
    return best


@dataclass(frozen=True)
class EvidenceWeights:
    """Relative importance of each criterion dimension."""

    skill: float = 0.4
    domain: float = 0.3
    seniority: float = 0.3
    role: float = 0.2
    name: float = 0.4


_WEIGHTS = EvidenceWeights()

# Multiplier applied to the final score when a candidate's known experience
# exceeds the requested maximum (e.g. a 7-year profile for a "junior 0-2 ans"
# query). Strong but non-zero so the profile stays visible, just ranked low.
_OVER_CAP_PENALTY: Final[float] = 0.4

# Closed vocabulary of criterion keys the LLM may order in `ranking_priority`.
RANKING_CRITERIA: Final[frozenset[str]] = frozenset(
    {"skill", "domain", "role", "seniority", "name"}
)
# Weight given to a dimension the LLM left OFF its priority ordering (so a
# listed criterion always outweighs an unlisted one). Only used when the LLM
# emits an ordering; otherwise the default EvidenceWeights apply.
PRIORITY_BASELINE: Final[float] = 0.25

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


def _canonical_term(term: str) -> str:
    """Resolve language normalisation + skill aliases for a term."""
    t = term.strip().lower()
    step1 = LANG_NORMALIZATIONS.get(t, t)
    return SKILL_ALIASES.get(step1, step1)


def _term_present(term: str, haystack: str) -> bool:
    """True if ``term`` (or any of its aliases) appears in the haystack.

    Single-word skills match as substrings (``"java"`` in ``"javafx"`` etc.);
    multi-word terms match when EVERY token is present (word-order tolerant).
    The canonical form and the original alias are both tried so "k8s" matches
    a profile that only mentions "kubernetes" and vice-versa.
    """
    term = term.strip().lower()
    if not term:
        return False

    candidates = {term, _canonical_term(term)}
    # Also try reverse lookup: if the query uses the canonical form, match aliases.
    for alias, canonical in SKILL_ALIASES.items():
        if canonical == term:
            candidates.add(alias)

    for t in candidates:
        if not t:
            continue
        if t in haystack:
            return True
        tokens = [tok for tok in _TOKEN_SPLIT_RE.split(t) if tok]
        if len(tokens) > 1 and all(tok in haystack for tok in tokens):
            return True
    return False


def evidence_score(
    haystack: str,
    *,
    skills: tuple[str, ...] | list[str],
    domains: tuple[str, ...] | list[str],
    role: str | None,
    candidate_min_years: int | None,
    required_min_years: int | None,
    required_max_years: int | None = None,
    domain_haystack: str | None = None,
    requested_name: str | None = None,
    candidate_name: str | None = None,
    priority: tuple[str, ...] | None = None,
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

    ``domain_haystack`` (when given) restricts the domain dimension to a
    high-signal surface (title + technical-document summary) so an incidental
    business word buried in a noisy skills blob does not earn domain credit.

    ``requested_name``/``candidate_name`` add a ``name`` dimension (token recall
    of the requested person's name against the candidate's), present only when a
    name was requested. ``priority`` is an LLM-supplied ordering of criterion
    keys (most important first, from ``RANKING_CRITERIA``); when given, each
    dimension's weight is taken FROM that ordering (``len-index`` for listed
    keys, ``PRIORITY_BASELINE`` for the rest) so the LLM — not a hardcoded weight
    table — decides relative importance. With ``requested_name`` and ``priority``
    both ``None`` the result is identical to the criteria-only score.
    """
    hay = haystack.lower()
    domain_hay = (domain_haystack if domain_haystack is not None else haystack).lower()
    # (key, weight, fraction-evidenced) per requested dimension.
    dims: list[tuple[str, float, float]] = []
    hits: set[str] = set()

    norm_skills = [s.lower() for s in skills if s and s.strip()]
    if norm_skills:
        found = [s for s in norm_skills if _term_present(s, hay)]
        for skill in found:
            hits.add(f"skill:{skill}")
        dims.append(("skill", weights.skill, len(found) / len(norm_skills)))

    norm_domains = [d for d in domains if d and d.strip()]
    if norm_domains:
        # Match ANY distinctive token of the (possibly verbose/ambiguous)
        # domain term — so "cib (corporate & investment banking)" is
        # evidenced by "SGCIB", "corporate", "investment", or "banking" —
        # but only within the high-signal domain surface.
        tokens = domain_match_tokens(norm_domains)
        domain_found = any(token in domain_hay for token in tokens)
        if domain_found:
            hits.add("domain")
        dims.append(("domain", weights.domain, 1.0 if domain_found else 0.0))

    if role and role.strip():
        low = role.lower()
        role_found = low in hay or all(tok in hay for tok in low.split())
        if role_found:
            hits.add("role")
        dims.append(("role", weights.role, 1.0 if role_found else 0.0))

    over_cap = False
    if required_min_years is not None or required_max_years is not None:
        effective_years = candidate_min_years
        # When explicit years data is absent, fall back to title-level inference
        # so a "Senior Lead" profile is not penalised against a "5+ years" query
        # merely because the structured experience field was not filled.
        if effective_years is None:
            effective_years = infer_years_from_title(hay)
        meets_min = required_min_years is None or (
            effective_years is not None and effective_years >= required_min_years
        )
        # Unknown years can't disprove the cap, so only a KNOWN over-cap value
        # breaks the band (we never penalise an unknown).
        within_max = required_max_years is None or (
            effective_years is None or effective_years <= required_max_years
        )
        over_cap = (
            required_max_years is not None
            and effective_years is not None
            and effective_years > required_max_years
        )
        in_band = meets_min and within_max
        # Partial credit (0.5) when inferred from title only (less certain than
        # an explicit years figure), so a profile with explicit years still
        # outranks one where we guessed from the title.
        if in_band and effective_years is not None:
            hits.add("seniority")
            fraction = 1.0 if candidate_min_years is not None else 0.5
        else:
            fraction = 0.0
        dims.append(("seniority", weights.seniority, fraction))

    if requested_name and requested_name.strip():
        name_frac = name_match_score(requested_name, candidate_name)
        # Only an exact (all-tokens) name match counts as evidenced, so a
        # look-alike sharing one surname can never be a full match.
        if name_frac >= 1.0:
            hits.add("name")
        dims.append(("name", weights.name, name_frac))

    if not dims:
        return 0.0, hits
    # When the LLM supplies a priority ordering, the dimension weights come from
    # that ordering (listed -> len-index, unlisted -> baseline). Otherwise the
    # default EvidenceWeights apply unchanged. Generic over every dimension.
    if priority:
        weighted = [
            (
                float(len(priority) - priority.index(key))
                if key in priority
                else PRIORITY_BASELINE,
                fraction,
            )
            for key, _weight, fraction in dims
        ]
    else:
        weighted = [(weight, fraction) for _key, weight, fraction in dims]
    total_weight = sum(weight for weight, _ in weighted)
    score = sum(weight * fraction for weight, fraction in weighted) / total_weight
    # A candidate whose known experience exceeds the requested maximum (e.g. a
    # 7-year profile for a "junior 0-2 ans" search) is strongly penalised so it
    # cannot top the ranking, while staying visible rather than excluded.
    if over_cap:
        score *= _OVER_CAP_PENALTY
    return score, hits
