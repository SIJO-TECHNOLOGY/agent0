"""Provider-neutral candidate search intent and external evidence models.

These schemas are deliberately conservative: every external fact is optional
and defaults to "unknown"/empty. Nothing here invents candidate data — a field
is populated only when public evidence supports it.

Key SIJO distinction (see mission_analysis): EMPLOYMENT duration at one
employer is NOT the same as one CLIENT-MISSION duration. The models keep them
separate so a "Capgemini 2018–2025" record can never be reported as a single
confirmed 84-month client mission.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Tri-state (+ negative) evidence status shared by the qualification models.
#   confirmed — public evidence clearly establishes it
#   probable  — strong signals but not provable from public data
#   unknown   — public data is insufficient (NOT the same as "no")
#   no        — enough evidence to reasonably conclude it is absent
EvidenceStatus = Literal["confirmed", "probable", "unknown", "no"]


class CandidateSearchQuery(BaseModel):
    """Provider-neutral search intent shared by BoondManager and LinkedIn.

    Built from the interpreted intent. Carries the SIJO business defaults so
    downstream sources apply them without the recruiter restating them.
    """

    model_config = ConfigDict(extra="forbid")

    job_titles: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    optional_skills: list[str] = Field(default_factory=list)
    location: str | None = None
    radius_km: int | None = None
    companies: list[str] = Field(default_factory=list)
    min_experience_years: int | None = None
    limit: int = 20

    # SIJO defaults (configurable via Settings, never hardcoded downstream).
    prefer_consulting_profile: bool = True
    long_mission_threshold_months: int = 24


class Evidence(BaseModel):
    """A single grounded fact with its public source URL."""

    model_config = ConfigDict(extra="forbid")

    field: str
    value: str
    source_url: str = ""


class ExternalExperience(BaseModel):
    """One experience line parsed from a public profile.

    ``employer`` is who paid the person; ``client`` is the end-customer of a
    mission when the profile explicitly names one. They are distinct on
    purpose — see the module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    employer: str | None = None
    client: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration_months: int | None = None
    consulting_context: bool | None = None
    explicit_client_mission: bool | None = None


class LongMissionEvidence(BaseModel):
    """Whether the candidate shows a client mission >= the threshold."""

    model_config = ConfigDict(extra="forbid")

    status: EvidenceStatus = "unknown"
    max_duration_months: int | None = None
    employer: str | None = None
    client: str | None = None
    evidence_text: str | None = None
    source_url: str | None = None


class ConsultingProfileEvidence(BaseModel):
    """Whether the candidate appears to be a consultant/freelance profile."""

    model_config = ConfigDict(extra="forbid")

    status: EvidenceStatus = "unknown"
    evidence: list[str] = Field(default_factory=list)


class ExternalCandidateEvidence(BaseModel):
    """A structured external candidate discovered from public web pages."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["linkedin_web"] = "linkedin_web"
    profile_url: str
    full_name: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    location: str | None = None
    matched_skills: list[str] = Field(default_factory=list)
    experiences: list[ExternalExperience] = Field(default_factory=list)
    consulting_profile: ConsultingProfileEvidence = Field(
        default_factory=ConsultingProfileEvidence
    )
    long_mission: LongMissionEvidence = Field(default_factory=LongMissionEvidence)
    evidence: list[Evidence] = Field(default_factory=list)
    snippet: str = ""


class ExternalProfileMatch(BaseModel):
    """Result of trying to find a known candidate's public LinkedIn profile.

    ``probable`` / ``ambiguous`` matches are surfaced but NEVER auto-merged —
    only ``strong`` matches are treated as the same physical person.
    """

    model_config = ConfigDict(extra="forbid")

    confidence_level: Literal["strong", "probable", "ambiguous"]
    score: float
    profile_url: str | None = None
    matched_name: bool = False
    matched_company: bool = False
    matched_title: bool = False
    matched_location: bool = False
