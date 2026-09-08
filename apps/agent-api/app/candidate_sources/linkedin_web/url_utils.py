"""Validate and canonicalize public LinkedIn profile URLs.

Discovery must only accept public member-profile pages (``linkedin.com/in/…``)
and reject company/jobs/posts/pulse pages and non-LinkedIn hosts. Regional
subdomains (``fr.linkedin.com``) and tracking query strings are normalized so
the same person is never counted twice, and a canonical identifier lets us
dedupe across search queries and across Boond records.

Pure functions only — no network, no LLM.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, unquote

# A LinkedIn member profile lives under /in/<public-identifier>. Everything
# else on the domain (company, jobs, posts, pulse, school, …) is NOT a person.
_PROFILE_PATH_RE = re.compile(r"^/in/([^/?#]+)", re.IGNORECASE)

# Non-profile LinkedIn path prefixes we explicitly reject.
_REJECTED_PATH_PREFIXES = (
    "/company",
    "/jobs",
    "/posts",
    "/pulse",
    "/school",
    "/showcase",
    "/groups",
    "/feed",
    "/learning",
    "/events",
)


def _with_scheme(url: str) -> str:
    """Ensure a parseable absolute URL so a scheme-less input still splits.

    ``linkedin.com/in/john`` has no scheme, so urlsplit would put the host in
    the path. Prepend https:// when no scheme is present.
    """
    text = (url or "").strip()
    if not text:
        return text
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    return text


def _host(url: str) -> str:
    return (urlsplit(_with_scheme(url)).netloc or "").lower()


def is_linkedin_host(url: str) -> bool:
    """True when the URL's host is linkedin.com or a regional subdomain."""
    host = _host(url)
    if not host:
        return False
    host = host.split(":", 1)[0]  # strip any port
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _profile_identifier(url: str) -> str | None:
    """Return the lowercased public identifier of a /in/ profile, or None."""
    if not is_linkedin_host(url):
        return None
    path = urlsplit(_with_scheme(url)).path or ""
    # Some regional/localized URLs prefix the locale, e.g. /fr/in/john-doe.
    match = _PROFILE_PATH_RE.match(path)
    if match is None:
        locale_match = re.match(r"^/[a-z]{2}/in/([^/?#]+)", path, re.IGNORECASE)
        if locale_match is None:
            return None
        identifier = locale_match.group(1)
    else:
        identifier = match.group(1)
    identifier = unquote(identifier).strip().strip("/").lower()
    return identifier or None


def is_profile_url(url: str) -> bool:
    """True only for a public LinkedIn member profile page (/in/…)."""
    if not isinstance(url, str) or not url.strip():
        return False
    path = urlsplit(_with_scheme(url)).path or ""
    if any(path.lower().startswith(p) for p in _REJECTED_PATH_PREFIXES):
        return False
    return _profile_identifier(url) is not None


def canonical_profile_url(url: str) -> str | None:
    """Canonical ``https://www.linkedin.com/in/<id>`` form, or None.

    Strips scheme/host variations, locale prefixes, trailing slashes, tracking
    query strings and fragments so two links to the same person collapse to one
    identifier. Returns None for anything that is not a profile URL.
    """
    identifier = _profile_identifier(url)
    if identifier is None:
        return None
    return f"https://www.linkedin.com/in/{identifier}"


def canonical_identifier(url: str) -> str | None:
    """The bare public identifier used as the dedup key across sources."""
    return _profile_identifier(url)
