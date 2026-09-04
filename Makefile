# Mirror of the CI `gate` job. Run before pushing.
#
# The v1.1 release passed local pytest and still failed CI: two generated CARD.md
# files were stale because their profile.json had never been rewritten. Local
# tests cannot catch that — only regenerating and diffing can.

.PHONY: check test regen clean-check

check: test regen clean-check

test:
	uv run --all-extras ruff check .
	uv run --all-extras mypy
	uv run --all-extras agr validate
	uv run --all-extras python scripts/audit_usecases.py
	uv run --all-extras python scripts/check_readme_counts.py
	uv run --all-extras python scripts/check_doc_currency.py
	uv run --all-extras pytest -q

regen:
	uv run --all-extras python scripts/gen_cards.py
	uv run --all-extras python scripts/gen_scoreboard.py
	uv run --all-extras python scripts/gen_traces.py
	uv run --all-extras python scripts/check_readme_counts.py --fix
	uv run --all-extras python scripts/gen_contract_findings.py
	uv run --all-extras python scripts/gen_clone_report.py
	uv run --all-extras python scripts/gen_self_graded.py
	uv run --all-extras python scripts/audit_recordings.py --json reports/a4-stale-recordings.json
	uv run --all-extras python scripts/gen_spec_banners.py

# Everything a regen script writes must match the committed tree. profile.json is
# change-gated since R1-04, so it belongs on this list too: a diff there means the
# evidence behind a profile actually moved.
clean-check:
	@git diff --exit-code -- README.md CARDS.md 'graphs/**/CARD.md' 'graphs/**/profile.json' \
	  'docs/traces/**' docs/contract-findings.md 'reports/*.json' 'docs/agr-v*.md' \
	  || { echo "ERROR: generated docs are stale — commit the regenerated files"; exit 1; }
	@echo "OK: generated docs match the committed tree"
