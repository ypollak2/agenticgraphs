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
- CI gate (GitHub Actions): validate + audit + tests (all extras).
- **M1** eval harness: graph interpreter (routers, joins, bounded loops, contract
  asserts), MockRunner (golden fixtures) + LLMRunner (any OpenAI-compatible endpoint),
  `agr eval` writing `profile.json` with runner provenance; golden cases + passing
  provisional profiles for the 3 handcrafted graphs.
- **M2** mutation layer: `agr infuse` (gate-checked ability injection with
  `lineage.yaml` provenance) and `agr optimize` (deterministic hill-climb:
  duplicate-edge dedupe, sibling parallelization, measurement-driven max_steps
  tightening; reverts any operator that breaks golden cases).
- **M3**: `agr adapt` LangGraph codegen (self-contained source, structure compiled,
  behavior left as explicit NotImplementedError bindings) and `agr mcp` MCP server
  (`search_graphs`, `get_graph`, `instantiate`, `infuse_ability`; compatible with
  mcp SDK 1.x and 2.x).
