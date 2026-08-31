# Security Policy

## Reporting a vulnerability

Report privately via [GitHub Security Advisories](https://github.com/ypollak2/agenticgraphs/security/advisories/new).
Please do not open a public issue for an unfixed vulnerability.

Expect an acknowledgement within 72 hours and a fix or a decision within 14 days.

## The threat model

A graph is a **downloaded artifact**. You `pip install vitruvian-graphs`, you pull a
contributor's PR, you accept a graph an agent wrote over MCP — and then you type
`agr eval`. Every graph in this registry is therefore untrusted input, and the
security question for this project is: *what can a graph.yaml do to the machine
that evaluates it?*

Three surfaces answer that:

| Surface | Control |
|---|---|
| `edges[].when`, `verification[].assert`, `approval.contract`, `search.score` | AST allowlist (`agenticgraphs.safeexpr`), enforced at both `agr validate` and run time |
| `verification[].command` | Never runs unless the caller passes `--run-commands`; skipped commands are counted and reported, never treated as passing |
| Abilities with `risk: write` / `risk: execute` (e.g. `run_command`) | Unbound unless the caller passes `--allow-tools`; the risk level is declared in `abilities/<name>.yaml` |
| Autonomous registry writes | Refused unless `AGR_AUTONOMOUS=1`; execute-risk abilities additionally require `AGR_AUTONOMOUS_ALLOW_EXECUTE=1`; writes land on `auto/mutations`, never `main`, never pushed |

If you find a graph that reaches outside these, that is a vulnerability — report it.

## Known issue: expression evaluation before v0.9.4

**Affected: every checkout of this repository before v0.9.4. Fixed in v0.9.4.**

**Scope, stated precisely.** This project has never been published to a package
index — `pip install` was never a way to get it, under any of the three names the
`pyproject.toml` discusses. The only distribution channel was this public
repository, which at the time of the fix had no forks and no dependents. So the
population at risk is: anyone who cloned the repo and ran `agr eval`, `agr
optimize`, or the MCP server against a graph they did not write themselves, plus
CI on any pull request. That is a real exposure and the reason this section
exists — it is not a supply-chain incident, and describing it as one would be the
same kind of unearned claim the project's own contracts are audited for.

`edges[].when` and `verification[].assert` were evaluated with
`eval(expr, {"__builtins__": {}}, ns)`. Emptying `__builtins__` is not a sandbox:
`().__class__.__bases__[0].__subclasses__()` walks from a literal back to every
loaded class, `subprocess.Popen` among them. Any graph.yaml could therefore run
arbitrary code as the invoking user, with:

- **no opt-in** — the `--allow-tools` gate governs abilities, and never saw this path;
- **no warning** — `agr validate` accepted such a graph and reported `OK`;
- **reach into CI** — the `gate` workflow evaluates every graph in a PR, and the
  `publish` workflow holds `id-token: write` against PyPI;
- **reach through generated code** — `agr adapt` inlined the same `eval` into every
  emitted LangGraph, CrewAI, and AutoGen module.

### What changed in 0.9.4

`agenticgraphs.safeexpr` walks the parse tree and refuses anything outside a small
allowlist: boolean and comparison operators, attribute and subscript access,
literals, comprehensions, and calls to `len`/`all`/`any`/`sum`/`min`/`max`/`abs`/
`round` or a `.get`. Any attribute or name beginning with `_` is refused outright.

The same walk runs in three places, because one of them alone is not enough:

1. **`agr validate`** — a hostile graph fails the gate, so a reviewer and CI see a
   rejection rather than a green check.
2. **The runtime** — a refused expression raises `UnsafeExpression` rather than
   scoring as a failed assert. Blending into the pass rate is the one outcome that
   would let a hostile contribution look merely mediocre.
3. **Emitted code** — `agr adapt` inlines an equivalent guard, since the generated
   module is standalone by design and cannot import this package.

Regression coverage is in `tests/test_safeexpr.py`, which pins the known escapes,
the 214 expressions the registry actually uses, and the guard inside generated code.

### If you ran an untrusted graph on an affected checkout

Assume arbitrary code execution as the invoking user. Rotate any credential
reachable from that environment. If you merged a pull request that touched a
`graph.yaml` before v0.9.4, the `gate` workflow evaluated it — and the `publish`
workflow in the same repository holds `id-token: write` against PyPI, so that
trusted-publishing relationship is worth reviewing even though nothing was ever
published through it.
