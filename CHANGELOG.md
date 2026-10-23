# Changelog

## Unreleased

- Compile immutable Annotated numeric and length constraints, including nested
  values, dictionary keys and constructed dataclass results.
- Support namespaced dataclass field constraints with configuration snapshots,
  composition with Annotated rules and partial-input validation.
- Add explicit scalar loading conversions for signed decimal integers, finite
  floats and exact boolean strings; keep check/dump and dictionary keys strict.

## 0.1.0 — 2026-10-19

- Immutable compiled type plans with strict native checks and explicit JSON/Python
  construction and serialization modes.
- Primitives, UUIDs, enums, literals/unions, typed lists/dictionaries/tuples and
  ordinary nested dataclasses with defaults, factories and computed fields.
- Partial dataclass input validation, structured value-free errors, depth/size/error
  budgets and safe cached-subtree compilation bounds.
- Verified concurrent plan reuse, cross-platform checks, isolated distributions
  and OIDC Trusted Publishing; no runtime dependencies, Python 3.14+.
