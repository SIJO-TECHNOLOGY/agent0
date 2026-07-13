"""Unit tests for the generic recall-first search strategy.

These prove the anchor derivation and relaxation ladder are GENERIC — no
hardcoded skill/role/domain — across Java, C#, Business Analyst, DevOps,
and Project Manager style queries.
"""

from __future__ import annotations

import pytest

from app.services.search_strategy import (
    Anchors,
    build_recall_passes,
    classify_anchors,
    domain_match_tokens,
    evidence_score,
    infer_years_from_title,
    name_match_score,
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


def test_skill_multiword_matches_when_all_tokens_present() -> None:
    # A multi-word term (e.g. a domain phrase that leaked into entities, or
    # a real multi-word skill) matches when all tokens are present — tolerant
    # to "&"/"and" and word order.
    _, hits = evidence_score(
        "software engineer at corporate and investment banking sgcib",
        skills=("java", "corporate & investment banking"),
        domains=(),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
    )
    assert "skill:corporate & investment banking" in hits
    assert "skill:java" not in hits  # java genuinely absent here


def test_skill_single_word_substring_still_matches() -> None:
    _, hits = evidence_score(
        "javafx developer",
        skills=("java",),
        domains=(),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
    )
    assert "skill:java" in hits


def test_domain_dimension_is_scoped_to_high_signal_text() -> None:
    # Domain word only in the noisy full haystack (skills blob) -> no credit.
    _, hits = evidence_score(
        "java investment banking spring kafka",
        skills=("java",),
        domains=("banking",),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
        domain_haystack="java developer",
    )
    assert "domain" not in hits
    # Present in the high-signal domain surface -> credit.
    _, hits2 = evidence_score(
        "java developer",
        skills=("java",),
        domains=("banking",),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
        domain_haystack="software engineer in banking",
    )
    assert "domain" in hits2


def test_over_cap_candidate_is_penalised() -> None:
    # "junior 0-2 ans" → required_max_years=2. A 7-year profile must score far
    # below an in-band 1-year profile with the same skill match.
    over, hits = evidence_score(
        "python",
        skills=("python",),
        domains=(),
        role=None,
        candidate_min_years=7,
        required_min_years=None,
        required_max_years=2,
    )
    in_band, _ = evidence_score(
        "python",
        skills=("python",),
        domains=(),
        role=None,
        candidate_min_years=1,
        required_min_years=None,
        required_max_years=2,
    )
    assert "seniority" not in hits      # over-cap loses the seniority credit
    assert over < in_band               # and is strongly penalised
    assert over < 0.5                   # cannot be a near-perfect match


def test_within_cap_candidate_keeps_credit() -> None:
    score, hits = evidence_score(
        "python",
        skills=("python",),
        domains=(),
        role=None,
        candidate_min_years=2,
        required_min_years=None,
        required_max_years=2,
    )
    assert "seniority" in hits


def test_unknown_years_not_hit_by_over_cap_multiplier() -> None:
    # Unknown experience is "unproven" (seniority credit 0, like a min query),
    # but it must NOT take the over-cap multiplier — so it ranks above a KNOWN
    # over-cap profile.
    unknown, _ = evidence_score(
        "python", skills=("python",), domains=(), role=None,
        candidate_min_years=None, required_min_years=None, required_max_years=2,
    )
    over_cap, _ = evidence_score(
        "python", skills=("python",), domains=(), role=None,
        candidate_min_years=7, required_min_years=None, required_max_years=2,
    )
    assert unknown > over_cap


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
# name_match_score — requested name vs candidate name (token recall)
# ---------------------------------------------------------------------------


def test_name_match_exact_is_one_case_insensitive() -> None:
    assert name_match_score("Taher ben abdallah", "TAHER BEN ABDALLAH") == 1.0


def test_name_match_partial_surname_only() -> None:
    # Shares only "abdallah" of {taher, ben, abdallah}.
    assert name_match_score("Taher ben abdallah", "Abdallah Khirallah") == pytest.approx(
        1 / 3
    )


def test_name_match_two_of_three() -> None:
    assert name_match_score("Taher ben abdallah", "Moatez Ben Abdallah") == pytest.approx(
        2 / 3
    )


def test_name_match_zero_when_no_overlap_or_empty() -> None:
    assert name_match_score("Taher ben abdallah", "Jean Dupont") == 0.0
    assert name_match_score("", "Anyone") == 0.0
    assert name_match_score("Taher", None) == 0.0


# ---------------------------------------------------------------------------
# infer_years_from_title — seniority cross-check (item 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Senior Java Developer", 5),
        ("Lead Architect", 8),   # architect (8) > lead (7) — highest wins
        ("Principal Engineer", 9),
        ("junior developer", 1),
        ("Staff Software Engineer", 7),
        ("CTO", 12),
    ],
)
def test_infer_years_from_title(title: str, expected: int) -> None:
    assert infer_years_from_title(title) == expected


def test_infer_years_from_title_unknown_returns_none() -> None:
    assert infer_years_from_title("Software Developer") is None
    assert infer_years_from_title("") is None


# ---------------------------------------------------------------------------
# evidence_score seniority — title inference fallback
# ---------------------------------------------------------------------------


def test_seniority_inferred_from_title_when_no_years() -> None:
    # Candidate has no explicit years but title says "Senior" (≥5 years implied).
    # Query requires 5 years. Should still get partial seniority credit.
    score, hits = evidence_score(
        "senior java developer banking experience",
        skills=("java",),
        domains=(),
        role=None,
        candidate_min_years=None,   # no explicit years data
        required_min_years=5,
    )
    assert "seniority" in hits
    # Partial credit (0.5 × seniority weight), not full credit
    assert score > 0.0


def test_seniority_title_inference_gives_lower_score_than_explicit_years() -> None:
    # Same profile: explicit 7 years should outscore title-only inference
    score_explicit, _ = evidence_score(
        "senior java developer",
        skills=("java",),
        domains=(),
        role=None,
        candidate_min_years=7,
        required_min_years=5,
    )
    score_inferred, _ = evidence_score(
        "senior java developer",
        skills=("java",),
        domains=(),
        role=None,
        candidate_min_years=None,
        required_min_years=5,
    )
    assert score_explicit > score_inferred


# ---------------------------------------------------------------------------
# _term_present alias awareness (item 1)
# ---------------------------------------------------------------------------


def test_alias_k8s_matches_kubernetes_in_haystack() -> None:
    # Query uses "k8s", profile says "kubernetes"
    score, hits = evidence_score(
        "experienced with kubernetes and docker",
        skills=("k8s",),
        domains=(),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
    )
    assert "skill:k8s" in hits


def test_alias_kubernetes_matches_k8s_in_haystack() -> None:
    # Query uses canonical "kubernetes", profile says "k8s"
    score, hits = evidence_score(
        "k8s cluster management expert",
        skills=("kubernetes",),
        domains=(),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
    )
    assert "skill:kubernetes" in hits


def test_alias_js_matches_javascript_in_haystack() -> None:
    score, hits = evidence_score(
        "javascript react developer",
        skills=("js",),
        domains=(),
        role=None,
        candidate_min_years=None,
        required_min_years=None,
    )
    assert "skill:js" in hits


# ---------------------------------------------------------------------------
# evidence_score — name dimension + generic LLM-chosen primary boost
# ---------------------------------------------------------------------------


def _criteria_kwargs() -> dict:
    """A fixed criteria-only call (no name, no primary)."""
    return dict(
        skills=("java",),
        domains=("cib",),
        role="developer",
        candidate_min_years=10,
        required_min_years=10,
    )


def test_evidence_score_unchanged_without_name_or_priority() -> None:
    # No-regression guard: with requested_name=None and priority=None the score
    # equals the criteria-only call (new params are inert by default).
    hay = "java developer at sgcib"
    base, base_hits = evidence_score(hay, **_criteria_kwargs())
    same, same_hits = evidence_score(
        hay, **_criteria_kwargs(), requested_name=None, candidate_name=None, priority=None
    )
    assert (same, same_hits) == (base, base_hits)


def test_evidence_score_name_dimension_exact_match_is_a_hit() -> None:
    score, hits = evidence_score(
        "tech lead java backend",
        skills=("java",),
        domains=(),
        role=None,
        candidate_min_years=10,
        required_min_years=10,
        requested_name="Taher ben abdallah",
        candidate_name="TAHER BEN ABDALLAH",
    )
    assert "name" in hits  # exact (all tokens) -> evidenced
    assert score > 0.0


def test_evidence_score_partial_name_is_not_a_hit() -> None:
    _score, hits = evidence_score(
        "java developer",
        skills=("java",),
        domains=(),
        role=None,
        candidate_min_years=10,
        required_min_years=10,
        requested_name="Taher ben abdallah",
        candidate_name="Abdallah Khirallah",
    )
    assert "name" not in hits  # only a shared surname


def test_priority_ordering_is_generic_over_any_dimension() -> None:
    # Two candidates: A evidences the skill only, B the domain only. Whichever
    # dimension the LLM ranks higher should win — proving the ordering is
    # generic, not name-specific.
    a_hay = "java engineer"  # skill yes, domain no
    b_hay = "consultant at sgcib"  # domain yes, skill no
    kw = dict(skills=("java",), domains=("cib",), role=None,
              candidate_min_years=None, required_min_years=None)

    a_skill, _ = evidence_score(a_hay, **kw, priority=("skill", "domain"))
    b_skill, _ = evidence_score(b_hay, **kw, priority=("skill", "domain"))
    assert a_skill > b_skill  # skill ranked first -> skill candidate wins

    a_domain, _ = evidence_score(a_hay, **kw, priority=("domain", "skill"))
    b_domain, _ = evidence_score(b_hay, **kw, priority=("domain", "skill"))
    assert b_domain > a_domain  # domain ranked first -> domain candidate wins


def test_priority_lifts_exact_name_over_perfect_criteria() -> None:
    # The Taher case, at the scoring level: exact-name + Java + 10y outscores a
    # look-alike with perfect criteria once the LLM ranks name first.
    kw = dict(skills=("java",), domains=(), role="developer",
              candidate_min_years=10, required_min_years=10)
    priority = ("name", "skill", "seniority", "role")
    taher, _ = evidence_score(
        "tech lead java backend", **kw,
        requested_name="Taher ben abdallah", candidate_name="TAHER BEN ABDALLAH",
        priority=priority,
    )
    stranger, _ = evidence_score(
        "java developer", **kw,
        requested_name="Taher ben abdallah", candidate_name="Abdallah Khirallah",
        priority=priority,
    )
    assert taher > stranger


def test_priority_demotes_partial_match_coach_below_domain_dev() -> None:
    # The JEROME case: a java+seniority "coach" (no domain/role) must rank below
    # a java+CIB developer once the LLM ranks domain/role above seniority.
    kw = dict(skills=("java",), domains=("cib",), role="developer")
    priority = ("domain", "role", "skill", "seniority")
    coach, _ = evidence_score(
        "coach craft java", **kw,
        candidate_min_years=10, required_min_years=10, priority=priority,
    )  # java + 10y, no CIB, not a dev
    cib_dev, _ = evidence_score(
        "java developer at sgcib", **kw,
        candidate_min_years=10, required_min_years=10, priority=priority,
    )  # java + CIB + dev + 10y
    assert cib_dev > coach


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


def test_anchors_capture_person_name_without_polluting_domains() -> None:
    anchors = classify_anchors(
        ["Java"],
        {"role": "developer", "min_experience_years": "10"},
        skill_labels={"java"},
        name="Taher ben abdallah",
    )
    assert anchors.name == "Taher ben abdallah"
    # The name must NOT leak into skills/role/domains (it would skew ranking).
    assert anchors.skills == ("Java",)
    assert anchors.role == "developer"
    assert anchors.domains == ()
    # Skill stays the primary keyword anchor; the name is a separate first pass.
    assert anchors.primary == "Java"
    assert anchors.is_empty() is False


def test_anchors_name_only_is_not_empty() -> None:
    anchors = classify_anchors([], {}, skill_labels=set(), name="Jane Doe")
    assert anchors.name == "Jane Doe"
    assert anchors.is_empty() is False
    # No skill/role/domain -> primary is None, but the ladder still has the name.
    assert anchors.primary is None


def test_anchors_blank_name_is_ignored() -> None:
    anchors = classify_anchors(["Java"], {}, skill_labels={"java"}, name="   ")
    assert anchors.name is None


# ---------------------------------------------------------------------------
# build_recall_passes — focused → broaden, drops filters, no boolean text
# ---------------------------------------------------------------------------


def test_ladder_is_keyword_only_and_recall_first() -> None:
    anchors = Anchors(skills=("java",), role="developer", domains=("cib",))
    passes = build_recall_passes(anchors, schema_fields=_SCHEMA_FIELDS)

    # First pass combines the discriminating content anchors (domain + skill),
    # so a candidate matching both surfaces at the top.
    assert passes[0].label == "combined"
    assert passes[0].relaxed is False
    assert passes[0].inputs["keywords"] == "cib java"
    # The single-skill primary pass still follows as a relaxation.
    assert any(p.label == "primary" and p.inputs.get("keywords") == "java" for p in passes)

    # The structured id filters are NEVER used (they can kill recall).
    for p in passes:
        assert "tools" not in p.inputs
        assert "experiences" not in p.inputs
        assert "keywords" in p.inputs


def test_combined_pass_skipped_for_single_content_term() -> None:
    # Only one content anchor → nothing to combine → primary is first (unchanged).
    anchors = Anchors(skills=("java",), role=None, domains=())
    passes = build_recall_passes(anchors, schema_fields=_SCHEMA_FIELDS)
    assert passes[0].label == "primary"
    assert all(p.label != "combined" for p in passes)


def test_combined_pass_excludes_generic_role_words() -> None:
    # The role must NOT be folded into the combined keyword query (noisy union).
    anchors = Anchors(skills=("java",), role="tech lead", domains=("amundi",))
    passes = build_recall_passes(anchors, schema_fields=_SCHEMA_FIELDS)
    combined = next(p for p in passes if p.label == "combined")
    assert combined.inputs["keywords"] == "amundi java"
    assert "lead" not in str(combined.inputs["keywords"]).lower()
    # The role still drives the title pass (not the resumeTd content union).
    assert any(
        p.inputs.get("keywords") == "tech lead"
        and p.inputs.get("keywordsType") == "titleSkills"
        for p in passes
    )
    # No pass ever carries boolean keyword syntax.
    for p in passes:
        kw = str(p.inputs.get("keywords", ""))
        assert " OR " not in kw and "(" not in kw and ")" not in kw


def test_ladder_searches_name_first_when_present() -> None:
    anchors = Anchors(
        skills=("java",), role="developer", domains=("cib",), name="Taher ben abdallah"
    )
    passes = build_recall_passes(anchors, schema_fields=_SCHEMA_FIELDS)

    # Pass 0 is the name — strongest anchor, not relaxed, full-text resumeTd.
    assert passes[0].label == "name"
    assert passes[0].relaxed is False
    assert passes[0].inputs["keywords"] == "Taher ben abdallah"
    assert passes[0].inputs["keywordsType"] == "resumeTd"

    # The skill/role/domain ladder still follows as the labeled relaxation,
    # and the skill primary slot is unchanged (no skills[0] dropped).
    assert any(
        p.label == "primary" and p.inputs.get("keywords") == "java" for p in passes
    )
    # The combined pass follows the name and carries both content anchors.
    assert any(
        p.label == "combined" and p.inputs.get("keywords") == "cib java" for p in passes
    )


def test_ladder_without_name_starts_with_combined() -> None:
    # A query with no person name and ≥2 content anchors starts with the
    # combined pass, never a "name" pass.
    anchors = Anchors(skills=("java",), role="developer", domains=("cib",))
    passes = build_recall_passes(anchors, schema_fields=_SCHEMA_FIELDS)
    assert passes[0].label == "combined"
    assert all(p.label != "name" for p in passes)


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
