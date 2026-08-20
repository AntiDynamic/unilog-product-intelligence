"""Manufacturer profile registry and candidate route repository."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from unilog_product_intelligence.retrieval.core import _same_or_subdomain

if TYPE_CHECKING:
    from unilog_product_intelligence.retrieval.source_discovery import (
        ManufacturerRetrievalProfile,
    )


class ManufacturerRegistry:
    """Thread-safe catalog of manufacturer retrieval profiles and learned candidate routes.

    Key Invariant:
      Learned candidate routes NEVER bypass SourceVerifier. Any candidate URL produced
      from a learned route template must pass strict HTTP fetch, MPN normalization,
      and identity matching (score >= 0.6) before being accepted.

    Static audited profiles always take precedence over learned dynamic templates.
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
        self._learned_routes: dict[str, list[str]] = {}  # mfg_name.casefold() -> list of templates
        self._learned_domains: dict[str, set[str]] = {}  # mfg_name.casefold() -> set of domains
        self._lock = threading.Lock()

    def get_profile_by_domain(
        self, domains: tuple[str, ...]
    ) -> ManufacturerRetrievalProfile | None:
        """Find a profile where any input domain matches a profile's verified domains."""
        for profile in self._static_profiles:
            if any(
                any(_same_or_subdomain(d, prof_d) for prof_d in profile.domains)
                for d in domains
            ):
                return profile
        return None

    def get_profile(self, manufacturer: str) -> ManufacturerRetrievalProfile | None:
        """Retrieve static profile or synthesize from learned routes."""
        key = manufacturer.casefold().strip()
        if key in self._profiles_by_name:
            return self._profiles_by_name[key]

        with self._lock:
            routes = tuple(self._learned_routes.get(key, ()))
            domains = tuple(self._learned_domains.get(key, ()))

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

    def learn_candidate_route(
        self,
        manufacturer: str,
        domain: str,
        route_template: str,
    ) -> None:
        """Record a verified URL template as a future candidate pattern.

        Only templates containing '{mpn}' are valid.
        Never alters static audited profiles.
        """
        if "{mpn}" not in route_template:
            return

        key = manufacturer.casefold().strip()
        if key in self._profiles_by_name:
            # Do not overwrite audited static profiles
            return

        with self._lock:
            routes = self._learned_routes.setdefault(key, [])
            if route_template not in routes:
                routes.append(route_template)
            if domain:
                domains = self._learned_domains.setdefault(key, set())
                domains.add(domain.casefold().strip())

    def register_profile(self, profile: ManufacturerRetrievalProfile) -> None:
        """Register a new static manufacturer profile."""
        with self._lock:
            self._static_profiles = (*self._static_profiles, profile)
            self._profiles_by_name[profile.name.casefold()] = profile


__all__ = ["ManufacturerRegistry"]
