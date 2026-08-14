# ADR 0011: Treat unloaded reference data as unavailable

## Decision

Manufacturer, brand, taxonomy, LOV, UOM, fraction, and rule registries return an explicit
unavailable status until approved reference files are loaded.

## Consequences

The application does not fabricate registry values or turn absence of data into an empty,
authoritative result.
