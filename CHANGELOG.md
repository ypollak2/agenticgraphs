# Changelog

## [0.1.0] — unreleased

### Added
- AGR v1 spec: JSON Schemas for graph, speciality, ability (15-domain taxonomy).
- Validator: schema conformance + MAST structural lint (dangling edges, unreachable
  nodes, unconditional back-edges, verifier-without-verification, unresolvable
  specialities/abilities).
- `agr` CLI: `list`, `search`, `validate`, `show`, `mermaid`, `profile`.
- 52 graphs across 15 domains (3 handcrafted, 49 pattern-template instantiations
  from the top-50 use cases).
- Use-case catalog: 112 audited entries; executable audit wired into pytest.
- 20 specialities, 20 abilities (risk-leveled, MCP-bindable).
- CI gate (GitHub Actions): validate + audit + tests.
