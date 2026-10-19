# Hindsight v1.0 vs v0.10

## Core conclusion

Hindsight v1.0.0 is primarily the stable release line for the mature v0.10 system, rather than a ground-up architectural rewrite.

The major product capabilities accumulated across v0.10.0 through v0.10.3. The v1.0.0 cut packaged that behavior as a stable public baseline and added final reliability, compatibility, and integration hardening.

## Timeline

- v0.10.0: September 14, 2026
- v0.10.3: October 8, 2026
- v1.0.0: October 13, 2026

## What v0.10 introduced and developed

The v0.10 line included several API and extension changes, including a new mental-model list response shape, removal of the bank profile and background endpoints, and removal of the `count_chunks` memory-extension hook.

It also added or expanded attachments, native MCP knowledge-base tools, bank aliases, per-caller tag scopes, tag-filtered entity and knowledge-base views, multi-LLM chain controls, per-scope consolidation strategies, provider support, Oracle support, streaming transfer, and operational metrics.

## What changed by v1.0.0

The v1.0.0 release retained the same core retain, recall, reflect, consolidation, and storage architecture.

The final changes focused on production behavior: temporary store-capacity failures now return `503` with `Retry-After` instead of an incorrect `500`; clients and the CLI tolerate new response fields and documented enum values; retain and integration error paths were hardened; and several integration behaviors were corrected.

All core artifacts were versioned as `1.0.0`, including the Python packages, npm wrapper, Rust CLI, and Helm chart.

## Practical upgrade guidance

For a new deployment, use v1.0.0 as the stable baseline.

For an existing v0.10 deployment, treat the upgrade as a cumulative v0.10 migration followed by the v1.0.0 packaging and hardening cut. Upgrade from the latest v0.10.3 where possible, review the v0.10 breaking changes, rehearse database migrations, and run API and client contract checks.

The largest conceptual difference is release maturity and compatibility expectations. The largest behavioral differences are between v0.10.0 and v0.10.3; the delta from v0.10.3 to v1.0.0 is comparatively small.
