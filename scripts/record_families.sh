#!/bin/zsh
# Record the registry against each model family in turn, one at a time.
#
# Two things this handles that a bare sweep does not:
#
# 1. **Sequence.** Two recorders sharing one Ollama server thrash it — every
#    slowdown in this project traced to concurrent access, including a 15-minute
#    hang on a single graph. Families run strictly one after another.
# 2. **Kills.** The sweep has been SIGKILLed repeatedly under memory pressure.
#    This re-checks the per-model gap and restarts, so a kill costs the run in
#    flight rather than the campaign.
#
# Exits when every listed model has full n=3 coverage.
cd /Users/yaliandrona/Projects/agenticgraphs
export AGR_LLM_BASE_URL=http://localhost:11434/v1
S=/private/tmp/claude-501/-Users-yaliandrona/0caf6bfb-ebc7-450c-98aa-62f983fd7244/scratchpad
MODELS=(lfm2.5:8b qwen3.8:latest)

gap () { AGR_LLM_MODEL=$1 AGR_TARGET_SAMPLES=$2 uv run python scripts/recording_gap.py 2>/dev/null | grep -c . }

for round in {1..40}; do
  done_all=1
  for m in $MODELS; do
    # Breadth before depth, WITHIN each model. A complete n=1 pass says something
    # about all 83 graphs; three samples over the first 30 says something about a
    # slice, and reading a rate off a slice is what live-coverage.md exists to
    # prevent. For a second family that matters more, not less: the cross-family
    # verdict (bad contract vs weak model) needs every graph, not deep data on few.
    for t in 1 2 3; do
      n=$(gap $m $t)
      [ "$n" -eq 0 ] && continue
      done_all=0
      echo "=== [$round] $m n=$t: $n graphs remaining ===" >> $S/record.log
      # One graph per invocation: a crash loses one graph, not the pass.
      AGR_LLM_MODEL=$m AGR_TARGET_SAMPLES=$t uv run python scripts/recording_gap.py 2>/dev/null \
        | while read -r g; do
            [ -z "$g" ] && continue
            AGR_LLM_MODEL=$m AGR_SAMPLES=$t uv run python scripts/record_live.py "$g" >> $S/record.log 2>&1
          done
      break 2   # re-evaluate from the top after every pass
    done
  done
  [ "$done_all" -eq 1 ] && { echo "=== ALL FAMILIES COMPLETE ===" >> $S/record.log; break }
done
