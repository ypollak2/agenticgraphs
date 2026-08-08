# Mirror of the CI `gate` job. Run before pushing.
#
# The v1.1 release passed local pytest and still failed CI: two generated CARD.md
# files were stale because their profile.json had never been rewritten. Local
# tests cannot catch that — only regenerating and diffing can.

.PHONY: check test regen clean-check

check: test regen clean-check

test:
	uv run --all-extras agr validate
	uv run --all-extras python scripts/audit_usecases.py
	uv run --all-extras pytest -q

regen:
	uv run --all-extras python scripts/gen_cards.py
	uv run --all-extras python scripts/gen_scoreboard.py
	uv run --all-extras python scripts/gen_traces.py

# profile.json embeds today's date, so it is never byte-stable across days and is
# excluded here for the same reason CI excludes it.
clean-check:
	@git diff --exit-code -- README.md CARDS.md 'graphs/**/CARD.md' 'docs/traces/**' \
	  || { echo "ERROR: generated docs are stale — commit the regenerated files"; exit 1; }
	@echo "OK: generated docs match the committed tree"
