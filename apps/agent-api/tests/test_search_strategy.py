"""Unit tests for the generic recall-first search strategy.

These prove the anchor derivation and relaxation ladder are GENERIC — no
hardcoded skill/role/domain — across Java, C#, Business Analyst, DevOps,
and Project Manager style queries.
"""

from __future__ import annotations

from app.services.search_strategy import (
    Anchors,
    build_recall_passes,
    classify_anchors,
    domain_match_tokens,
    evidence_score,
    safe_keywords,
)


# ---------------------------------------------------------------------------
# domain_match_tokens — generic acronym/business-context handling
# ---------------------------------------------------------------------------


def test_domain_tokens_keep_acronym_and_expansion_words() -> None:
    tokens = domain_match_tokens(["cib (corporate & investment banking)"])
    assert "cib" in tokens  # original acronym preserved as evidence
    assert "banking" in tokens  # expansion words still matchable
    assert "and" not in tokens  # grammatical stopword dropped


def test_domain_tokens_generic_for_any_business_context() -> None:
    assert domain_match_tokens(["banking"]) == {"banking"}
    assert domain_match_tokens(["payments"]) == {"payments"}
    assert "insurance" in domain_match_tokens(["insurance"])


def test_evidence_score_acronym_matches_inside_word() -> None:
    # "cib" must be evidenced by "SGCIB" even though the user supplied the
    # verbose ambiguous form.
    score, hits = evidence_score(
        "software engineer at societe generale - sgcib",
        skills=(),
        domains=("cib (corporate & investment banking)",),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
    )
    assert "domain" in hits
    assert score == 1.0


# ---------------------------------------------------------------------------
# evidence_score — distinct criteria, seniority gating, domain substring
# ---------------------------------------------------------------------------


def test_evidence_score_rewards_more_criteria() -> None:
    full, _ = evidence_score(
        "java spring sgcib",
        skills=("java",),
        domains=("cib",),
        role=None,
        candidate_min_years=11,
        required_min_years=10,
    )
    skill_only, _ = evidence_score(
        "java spring",
        skills=("java",),
        domains=("cib",),
        role=None,
        candidate_min_years=3,
        required_min_years=10,
    )
    assert full == 1.0
    assert full > skill_only


def test_evidence_score_domain_substring_matches_sgcib() -> None:
    score, hits = evidence_score(
        "software engineer at societe generale - sgcib",
        skills=(),
        domains=("cib",),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
    )
    assert "domain" in hits
    assert score == 1.0


def test_evidence_score_seniority_below_required_earns_nothing() -> None:
    below, hits = evidence_score(
        "java",
        skills=("java",),
        domains=(),
        role=None,
        candidate_min_years=3,
        required_min_years=10,
    )
    assert "seniority" not in hits
    above, _ = evidence_score(
        "java",
        skills=("java",),
        domains=(),
        role=None,
        candidate_min_years=11,
        required_min_years=10,
    )
    # A 3-year profile must score strictly below an 11-year one.
    assert above > below


_SCHEMA_FIELDS = {
    "keywords",
    "keywordsType",
    "tools",
    "experiences",
    "page",
    "maxResults",
}


# ---------------------------------------------------------------------------
# safe_keywords — never emit boolean syntax
# ---------------------------------------------------------------------------


def test_safe_keywords_strips_boolean_and_parentheses() -> None:
    assert safe_keywords('("10 years" OR "10+ years")') == "10 years 10+ years"
    assert safe_keywords("java OR python") == "java python"
    assert safe_keywords("java AND spring") == "java spring"
    # A simple +term include operator is preserved.
    assert safe_keywords("+java CIB") == "+java CIB"


# ---------------------------------------------------------------------------
# classify_anchors — generic, dynamic, not hardcoded
# ---------------------------------------------------------------------------


def test_anchors_java_developer_in_cib() -> None:
    anchors = classify_anchors(
        ["Java", "CIB"],
        {"role": "developer", "domain": "CIB"},
        skill_labels={"java"},
    )
    assert anchors.skills == ("Java",)
    assert anchors.role == "developer"
    assert "CIB" in anchors.domains
    assert anchors.primary == "Java"


def test_anchors_csharp_developer_in_banking_not_java() -> None:
    anchors = classify_anchors(
        ["C#"],
        {"role": "developer", "domain": "banking"},
        skill_labels={"c#"},
    )
    # Proves the anchor is dynamic — C#, never a hardcoded Java.
    assert anchors.skills == ("C#",)
    assert anchors.primary == "C#"
    assert anchors.domains == ("banking",)


def test_anchors_business_analyst_in_payments_role_primary() -> None:
    anchors = classify_anchors(
        [],
        {"role": "Business Analyst", "domain": "payments"},
        skill_labels=set(),
    )
    assert anchors.skills == ()
    assert anchors.role == "Business Analyst"
    assert anchors.domains == ("payments",)
    assert anchors.primary == "Business Analyst"


def test_anchors_devops_aws_role_heuristic_fallback() -> None:
    # No role in constraints — "DevOps" is recognised by the suffix
    # heuristic; AWS is a dictionary skill.
    anchors = classify_anchors(
        ["AWS", "DevOps"],
        {},
        skill_labels={"aws"},
    )
    assert anchors.skills == ("AWS",)
    assert anchors.role == "DevOps"
    assert anchors.primary == "AWS"


def test_anchors_project_manager_finance() -> None:
    anchors = classify_anchors(
        [],
        {"role": "Project Manager", "domain": "finance"},
        skill_labels=set(),
    )
    assert anchors.role == "Project Manager"
    assert anchors.domains == ("finance",)


# ---------------------------------------------------------------------------
# build_recall_passes — focused → broaden, drops filters, no boolean text
# ---------------------------------------------------------------------------


def test_ladder_is_keyword_only_and_recall_first() -> None:
    anchors = Anchors(skills=("java",), role="developer", domains=("cib",))
    passes = build_recall_passes(anchors, schema_fields=_SCHEMA_FIELDS)

    assert passes[0].label == "primary"
    assert passes[0].relaxed is False
    assert passes[0].inputs["keywords"] == "java"

    # The structured id filters are NEVER used (they can kill recall).
    for p in passes:
        assert "tools" not in p.inputs
        assert "experiences" not in p.inputs
        assert "keywords" in p.inputs

    # Role + domain passes exist somewhere in the ladder.
    assert any(
        p.inputs.get("keywords") == "developer"
        and p.inputs.get("keywordsType") == "titleSkills"
        for p in passes
    )
    assert any(p.inputs.get("keywords") == "cib" for p in passes)

    # No pass ever carries boolean keyword syntax.
    for p in passes:
        kw = str(p.inputs.get("keywords", ""))
        assert " OR " not in kw and "(" not in kw and ")" not in kw


def test_ladder_is_bounded() -> None:
    anchors = Anchors(
        skills=("a", "b", "c", "d", "e", "f"), role="dev", domains=("x", "y")
    )
    passes = build_recall_passes(
        anchors, schema_fields=_SCHEMA_FIELDS, max_passes=5
    )
    assert len(passes) <= 5


def test_ladder_empty_when_no_keywords_field() -> None:
    anchors = Anchors(skills=("java",), role=None, domains=())
    # Schema without a keywords field -> nothing recall-able to build.
    passes = build_recall_passes(anchors, schema_fields={"page"})
    assert passes == []
