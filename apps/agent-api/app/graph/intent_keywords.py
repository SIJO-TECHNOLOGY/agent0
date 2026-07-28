"""Deterministic keyword heuristics used by the MVP planner.

The MVP avoids LLM calls and uses simple keyword detection so the
workflow remains deterministic and testable. Real LLM-backed
analysis can replace these heuristics later behind the same node
interface.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")

# ---------------------------------------------------------------------------
# Skill aliases — maps common abbreviations / alternate spellings to their
# canonical lowercase form used in BoondManager skill labels and scoring.
# Keys are the raw token (post-accent-strip, lowercase); values are canonical.
# ---------------------------------------------------------------------------
SKILL_ALIASES: Final[dict[str, str]] = {
    # JavaScript ecosystem
    "js": "javascript",
    "ts": "typescript",
    "nodejs": "node.js",
    "node": "node.js",
    "reactjs": "react",
    "vuejs": "vue",
    "react.js": "react",
    "vue.js": "vue",
    "nextjs": "next.js",
    "nuxtjs": "nuxt.js",
    # Related spellings that must still count now that skill matching is
    # token-based (never substrings — "java" must not match "javascript").
    "angularjs": "angular",
    "javafx": "java",
    # Cloud / infra
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "tf": "terraform",
    "gcp": "google cloud",
    "aws": "amazon web services",
    # Databases
    "pg": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "es": "elasticsearch",
    # ML / data
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "sklearn": "scikit-learn",
    "tf2": "tensorflow",
    # CI/CD
    "gh": "github",
    "gh-actions": "github actions",
    "gitlab-ci": "gitlab",
    "jenkins-x": "jenkins",
    # Languages
    "py": "python",
    "rb": "ruby",
    "cs": "c#",
    "cpp": "c++",
    "golang": "go",
    # French → English tech terms (multilinguisme item 7)
    "apprentissage automatique": "machine learning",
    "traitement du langage": "natural language processing",
    "vision artificielle": "computer vision",
    "nuage": "cloud",
    "conteneur": "docker",
    "conteneurs": "docker",
    "orchestration": "kubernetes",
    "base de donnees": "database",
    "bases de donnees": "database",
    "developpement web": "web development",
    "developpement mobile": "mobile development",
    "intelligence artificielle": "artificial intelligence",
    "ia": "artificial intelligence",
}

# ---------------------------------------------------------------------------
# Language normalisation — French technical role/domain terms mapped to their
# English equivalents so FR queries score consistently against EN profiles.
# Applied at tokenisation time in extract_keywords().
# ---------------------------------------------------------------------------
LANG_NORMALIZATIONS: Final[dict[str, str]] = {
    # Roles
    "developpeur": "developer",
    "ingenieur": "engineer",
    "architecte": "architect",
    "analyste": "analyst",
    "concepteur": "designer",
    "testeur": "tester",
    "auditeur": "auditor",
    "administrateur": "administrator",
    "responsable": "manager",
    "directeur": "director",
    "chef": "lead",
    # Domains / sectors
    "banque": "banking",
    "assurance": "insurance",
    "finance": "finance",
    "paiement": "payment",
    "paiements": "payments",
    "sante": "healthcare",
    "immobilier": "real estate",
    "energie": "energy",
    "telecom": "telecom",
    "telecoms": "telecom",
    "transport": "transport",
    "logistique": "logistics",
    "commerce": "retail",
    "distribution": "retail",
    # Generic tech words
    "securite": "security",
    "reseau": "network",
    "reseaux": "network",
    "systeme": "system",
    "systemes": "system",
    "donnees": "data",
    "performance": "performance",
    "integration": "integration",
    "migration": "migration",
    "transformation": "transformation",
    "numerique": "digital",
    "agile": "agile",
    "scrum": "scrum",
    "devops": "devops",
}

# Matches phrases like "candidate id 41924", "candidateId=41924", "candidate#41924",
# and the common typo "cadidate id 41924". Requires an "id"-style anchor so we
# don't over-trigger on stray numbers.
_CANDIDATE_ID_RE: re.Pattern[str] = re.compile(
    r"\b(?:candidate|cadidate)\s*(?:id|ids|_id|#)\s*[:=]?\s*(\d+)\b",
    re.IGNORECASE,
)

_SENIORITY_TERMS: Final[dict[str, str]] = {
    "junior": "junior",
    "intermediate": "intermediate",
    "mid": "intermediate",
    "senior": "senior",
    "lead": "lead",
    "principal": "principal",
}

_TYPE_HINTS: Final[dict[str, str]] = {
    "candidate": "search_consultants",
    "candidates": "search_consultants",
    "consultant": "search_consultants",
    "consultants": "search_consultants",
    "dev": "search_consultants",
    "devs": "search_consultants",
    "developer": "search_consultants",
    "developers": "search_consultants",
    "engineer": "search_consultants",
    "engineers": "search_consultants",
    "profile": "search_consultants",
    "profiles": "search_consultants",
    "candidat": "search_consultants",
    "candidats": "search_consultants",
    "profil": "search_consultants",
    "profils": "search_consultants",
    "développeur": "search_consultants",
    "developpeur": "search_consultants",
    "développeurs": "search_consultants",
    "developpeurs": "search_consultants",
    "ingénieur": "search_consultants",
    "ingenieur": "search_consultants",
    "ingénieurs": "search_consultants",
    "ingenieurs": "search_consultants",
    "ressource": "search_consultants",
    "ressources": "search_consultants",
    "project": "search_projects",
    "projects": "search_projects",
    "mission": "search_projects",
    "missions": "search_projects",
    "opportunity": "search_opportunities",
    "opportunities": "search_opportunities",
    "opportunite": "search_opportunities",
    "opportunites": "search_opportunities",
    "deal": "search_opportunities",
    "deals": "search_opportunities",
}

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        # Articles and conjunctions
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "with",
        "from",
        # Verbs/imperatives that frame the request
        "find",
        "search",
        "show",
        "list",
        "get",
        "fetch",
        "give",
        # Pronouns / determiners
        "me",
        "my",
        "i",
        "his",
        "her",
        "their",
        "they",
        "we",
        "us",
        "you",
        "your",
        "him",
        # Auxiliaries / modals
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "should",
        "would",
        "could",
        "can",
        "must",
        "may",
        "might",
        "will",
        "shall",
        # Question / connector words
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        # Common adverbs / prepositions
        "in",
        "on",
        "to",
        "at",
        "by",
        "as",
        "than",
        "then",
        # Quantifiers that don't help keyword filtering
        "any",
        "all",
        "more",
        "less",
        "most",
        "few",
        "many",
        "much",
        # Search-specific noise
        "available",
        "next",
        "this",
        "that",
        "year",
        "years",
        "yrs",
        "month",
        "months",
        "experience",
        "experiences",
        "last",
        "first",
        "previous",
        "current",
        "about",
        "around",
        "looking",
        "need",
        "want",
        "wanted",
        "wanting",
        # French request framing
        "trouve",
        "trouver",
        "cherche",
        "chercher",
        "recherche",
        "rechercher",
        "donne",
        "donner",
        "montre",
        "montrer",
        "affiche",
        "afficher",
        "liste",
        "lister",
        "moi",
        "me",
        "mon",
        "ma",
        "mes",
        "nous",
        "vous",
        "votre",
        "vos",
        "un",
        "une",
        "des",
        "de",
        "du",
        "d",
        "le",
        "la",
        "les",
        "et",
        "ou",
        "avec",
        "pour",
        "sur",
        "dans",
        "en",
        "au",
        "aux",
        "ce",
        "ces",
        "cet",
        "cette",
        "qui",
        "quoi",
        "quand",
        "comment",
        "sont",
        "est",
        "etre",
        "avoir",
        "besoin",
        "veux",
        "voudrais",
        "peux",
        "peut",
        "peuvent",
        "disponible",
        "disponibles",
        "expérience",
        "experience",
        "ans",
    }
)


_YEARS_EXPERIENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,2})\s*\+?\s*(?:year|yr|an)s?\b",
    re.IGNORECASE,
)


def tokenize(query: str) -> list[str]:
    """Return lowercase tokens from a query."""
    normalized = unicodedata.normalize("NFKD", query)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return [match.group(0).lower() for match in WORD_RE.finditer(without_accents)]


def _normalize_token(token: str) -> str:
    """Apply language normalisation then skill alias resolution to a single token.

    Lang normalisation maps French technical words to their English equivalents
    (e.g. "developpeur" → "developer") so queries in French score consistently
    against English-labelled profiles.  Alias resolution then maps common
    abbreviations to their canonical form (e.g. "k8s" → "kubernetes").
    Both tables are applied in order so a French abbreviation (e.g. "ia" →
    "artificial intelligence") is handled correctly.
    """
    step1 = LANG_NORMALIZATIONS.get(token, token)
    return SKILL_ALIASES.get(step1, step1)


def extract_keywords(query: str) -> list[str]:
    """Return de-duplicated content keywords useful as tool inputs."""
    tokens = tokenize(query)
    keywords: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in _STOPWORDS or token in _SENIORITY_TERMS:
            continue
        if token in _TYPE_HINTS:
            continue
        normalized = _normalize_token(token)
        if normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(normalized)
    return keywords


def extract_seniority(query: str) -> str | None:
    """Return a normalized seniority label if present in the query."""
    for token in tokenize(query):
        normalized = _SENIORITY_TERMS.get(token)
        if normalized:
            return normalized
    return None


def extract_min_years_experience(query: str) -> int | None:
    """Return the smallest integer ``N`` mentioned as "<N> years" of experience.

    Accepts forms like "10 years experience", "more than 10 years", "10+ yrs".
    Returns ``None`` when no number is present so callers don't invent a
    filter the MCP server can't satisfy reliably.
    """
    matches = _YEARS_EXPERIENCE_RE.findall(query)
    if not matches:
        return None
    try:
        values = [int(value) for value in matches]
    except (TypeError, ValueError):
        return None
    return min(values) if values else None


_UNIT_RE: Final[str] = r"(?:year|yr|an|année|annee)s?"
# "0-2 ans", "3 à 5 years", "3 to 5 yrs"
_RANGE_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(\d{{1,2}})\s*(?:-|–|—|à|a|to)\s*(\d{{1,2}})\s*\+?\s*{_UNIT_RE}\b",
    re.IGNORECASE,
)
# upper bound: "moins de 3 ans", "less than 3 years", "jusqu'à 2 ans", "max 3 ans"
_MAX_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:moins\s+de|less\s+than|jusqu['’]?\s*[aà]|up\s+to|max(?:imum)?|au\s+plus)\s*"
    rf"(\d{{1,2}})\s*\+?\s*{_UNIT_RE}\b",
    re.IGNORECASE,
)
# lower bound: "plus de 5 ans", "more than 5 years", "au moins 5 ans", "5+ ans"
_MIN_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:plus\s+de|more\s+than|au\s+moins|at\s+least|min(?:imum)?)\s*(\d{{1,2}})\s*{_UNIT_RE}\b"
    rf"|\b(\d{{1,2}})\s*\+\s*{_UNIT_RE}\b",
    re.IGNORECASE,
)
# Seniority labels → (min_years, max_years) band, used only when the query
# gives no explicit number. Junior ≤2, Confirmed 3-5, Senior ≥5.
_SENIORITY_BANDS: Final[dict[str, tuple[int | None, int | None]]] = {
    "junior": (None, 2),
    "intermediate": (3, 5),
    "senior": (5, None),
    "lead": (7, None),
    "principal": (8, None),
}


def extract_experience_bounds(
    query: str, seniority: str | None = None
) -> tuple[int | None, int | None]:
    """Return (min_years, max_years) requested by the query.

    Explicit numbers win over the seniority-label fallback. Recognises ranges
    ("0-2 ans"), upper bounds ("moins de 3 ans"), lower bounds ("5+ ans",
    "plus de 5 ans"), and a bare "<N> years" (treated as a minimum, preserving
    the previous behaviour). When the query carries no number, a seniority word
    ("junior"/"senior") maps to a band.
    """
    lo: int | None = None
    hi: int | None = None

    range_match = _RANGE_RE.search(query)
    if range_match:
        a, b = int(range_match.group(1)), int(range_match.group(2))
        lo, hi = min(a, b), max(a, b)
    else:
        max_match = _MAX_RE.search(query)
        if max_match:
            hi = int(max_match.group(1))
        min_match = _MIN_RE.search(query)
        if min_match:
            lo = int(min_match.group(1) or min_match.group(2))
        if lo is None and hi is None:
            # A bare "<N> years" with no qualifier → minimum (legacy behaviour).
            lo = extract_min_years_experience(query)

    if lo is None and hi is None and seniority:
        band = _SENIORITY_BANDS.get(seniority)
        if band is not None:
            lo, hi = band

    return lo, hi


def extract_candidate_id(query: str) -> int | None:
    """Return a candidate ID parsed from the query, or None.

    Accepts forms such as "candidate id 41924", "candidateId=41924",
    and the typo "cadidate id 41924". Requires an "id"-style anchor
    to avoid matching unrelated numbers in the query.
    """
    match = _CANDIDATE_ID_RE.search(query)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def detect_tools(query: str) -> list[str]:
    """Detect requested MCP tools from type hints in the query."""
    tools: list[str] = []
    seen: set[str] = set()
    for token in tokenize(query):
        tool = _TYPE_HINTS.get(token)
        if tool and tool not in seen:
            seen.add(tool)
            tools.append(tool)
    return tools
