# ADR 0017: Source caching and content hashing

Status: accepted

Canonical URLs and content hashes deduplicate retrieval and parsing. Fresh cache entries are reused; stale entries are observable and refreshable. Production persistence belongs in the Phase 5 retrieval tables; the local implementation is an in-process adapter for deterministic tests.
