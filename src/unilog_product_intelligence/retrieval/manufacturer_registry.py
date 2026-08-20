"""Manufacturer profile registry and verified route repository."""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from unilog_product_intelligence.domain.truth import SourceAuthority
from unilog_product_intelligence.retrieval.core import _same_or_subdomain

if TYPE_CHECKING:
    from unilog_product_intelligence.retrieval.source_discovery import (
        ManufacturerRetrievalProfile,
    )


class RegistryTrustError(ValueError):
    """Raised when an untrusted or invalid route is submitted to the registry."""


@dataclass(frozen=True)
class VerifiedRoute:
    """A route verified by evidence against an authoritative or secondary source.

    Attributes
    ----------
    route_template:
        URL pattern containing the ``{mpn}`` placeholder.
    domain:
        The verified domain this route belongs to.
    evidence_id:
        The EvidenceReference ID that verified this route pattern.
    source_authority:
        Authority tier of the verifying source.
    verified_at:
        Epoch timestamp when this route was verified.
    expires_at:
        Epoch timestamp when this route's trust expires (None for no expiration).
    """

    route_template: str
    domain: str
    evidence_id: str
    source_authority: SourceAuthority = SourceAuthority.AUTHORITATIVE
    verified_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def is_expired(self, now: float | None = None) -> bool:
        """Return True if this route has an expiration timestamp in the past."""
        current_time = now if now is not None else time.time()
        return self.expires_at is not None and current_time > self.expires_at


class ManufacturerRegistry:
    """Thread-safe catalog of manufacturer retrieval profiles and verified candidate routes.

    Key Invariants:
      1. Verified candidate routes NEVER bypass SourceVerifier. Any candidate URL produced
         from a learned route template must pass strict HTTP fetch, MPN normalization,
         and identity matching (score >= 0.6) before being accepted.
      2. Routes must cite a valid evidence_id from a verified extraction.
      3. Static audited profiles always take precedence over learned dynamic templates.
      4. Routes with TTLs expire automatically after expires_at.
    """

    def __init__(
        self,
        static_profiles: tuple[ManufacturerRetrievalProfile, ...] | None = None,
    ) -> None:
        if static_profiles is None:
            # Lazy import to avoid circular dependencies
            from unilog_product_intelligence.retrieval.source_discovery import (
                _RETRIEVAL_PROFILES,
            )

            static_profiles = _RETRIEVAL_PROFILES

        self._static_profiles: tuple[ManufacturerRetrievalProfile, ...] = static_profiles
        self._profiles_by_name: dict[str, ManufacturerRetrievalProfile] = {
            p.name.casefold(): p for p in static_profiles
        }
        self._verified_routes: dict[
            str, list[VerifiedRoute]
        ] = {}  # mfg_name.casefold() -> list of VerifiedRoute
        self._lock = threading.Lock()

    def get_profile_by_domain(
        self, domains: tuple[str, ...]
    ) -> ManufacturerRetrievalProfile | None:
        """Find a profile where any input domain matches a profile's verified domains."""
        for profile in self._static_profiles:
            if any(
                any(_same_or_subdomain(d, prof_d) for prof_d in profile.domains) for d in domains
            ):
                return profile
        return None

    def get_profile(
        self, manufacturer: str, *, now: float | None = None
    ) -> ManufacturerRetrievalProfile | None:
        """Retrieve static profile or synthesize from non-expired verified routes."""
        key = manufacturer.casefold().strip()
        if key in self._profiles_by_name:
            return self._profiles_by_name[key]

        with self._lock:
            routes_list = self._verified_routes.get(key, [])
            # Filter out expired routes
            valid_routes = [r for r in routes_list if not r.is_expired(now=now)]
            # Prune expired routes in place if any expired
            if len(valid_routes) != len(routes_list):
                self._verified_routes[key] = valid_routes

            routes = tuple(r.route_template for r in valid_routes)
            domains = tuple({r.domain for r in valid_routes if r.domain})

        if not routes and not domains:
            return None

        from unilog_product_intelligence.retrieval.source_discovery import (
            ManufacturerRetrievalProfile,
        )

        return ManufacturerRetrievalProfile(
            name=manufacturer,
            domains=domains,
            search_url_templates=(),
            direct_path_templates=routes,
            product_link_patterns=(),
        )

    def record_verified_route(
        self,
        manufacturer: str,
        domain: str,
        route_template: str,
        evidence_id: str,
        source_authority: SourceAuthority = SourceAuthority.AUTHORITATIVE,
        ttl_seconds: float | None = None,
    ) -> VerifiedRoute | None:
        """Record an evidence-backed URL template as a verified candidate route.

        Parameters
        ----------
        manufacturer:
            Manufacturer name.
        domain:
            Domain of the verified source.
        route_template:
            URL pattern containing the ``{mpn}`` placeholder.
        evidence_id:
            Non-empty EvidenceReference ID that validates this route.
        source_authority:
            Authority level of the source.
        ttl_seconds:
            Optional lifetime in seconds before this route expires.

        Returns
        -------
        VerifiedRoute | None
            The created VerifiedRoute, or None if the manufacturer has a static profile.
        """
        if "{mpn}" not in route_template:
            raise RegistryTrustError(
                f"Route template '{route_template}' must contain '{{mpn}}' placeholder."
            )
        if not evidence_id or not evidence_id.strip():
            raise RegistryTrustError(
                "A valid, non-empty evidence_id is required to record a verified route."
            )
        if not manufacturer or not manufacturer.strip():
            raise RegistryTrustError("Manufacturer name cannot be empty.")

        key = manufacturer.casefold().strip()
        if key in self._profiles_by_name:
            # Audited static profiles cannot be overridden
            return None

        clean_domain = domain.casefold().strip()
        now = time.time()
        expires_at = (now + ttl_seconds) if ttl_seconds is not None else None

        verified_route = VerifiedRoute(
            route_template=route_template,
            domain=clean_domain,
            evidence_id=evidence_id.strip(),
            source_authority=source_authority,
            verified_at=now,
            expires_at=expires_at,
        )

        with self._lock:
            routes = self._verified_routes.setdefault(key, [])
            # Deduplicate by template
            if not any(r.route_template == route_template for r in routes):
                routes.append(verified_route)

        return verified_route

    def learn_candidate_route(
        self,
        manufacturer: str,
        domain: str,
        route_template: str,
    ) -> None:
        """Deprecated shim for record_verified_route.

        Silently ignores invalid templates to maintain backward compatibility.
        """
        with contextlib.suppress(RegistryTrustError):
            self.record_verified_route(
                manufacturer=manufacturer,
                domain=domain,
                route_template=route_template,
                evidence_id="ev-learned-route",
            )

    def register_profile(self, profile: ManufacturerRetrievalProfile) -> None:
        """Register a new static manufacturer profile."""
        with self._lock:
            self._static_profiles = (*self._static_profiles, profile)
            self._profiles_by_name[profile.name.casefold()] = profile


__all__ = ["ManufacturerRegistry", "RegistryTrustError", "VerifiedRoute"]
