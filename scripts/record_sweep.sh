#!/bin/zsh
# Complete coverage first, depth second. An 18.6GB model plus the harness runs the
# machine out of memory within ~20 minutes, and the sweep has been SIGKILLed four
# times. Every kill costs only the run in flight, but a sweep that never finishes
# reports nothing — so this reaches n=1 across all 83 before going back for n=2
# and n=3. A complete one-sample baseline is worth more than a partial three-sample
# one, and the breadth report already grades a cell by its width.
cd /Users/yaliandrona/Projects/agenticgraphs
export AGR_LLM_BASE_URL=http://localhost:11434/v1
: "${AGR_LLM_MODEL:=qwen3-coder:30b}"   # override to record a second family
export AGR_LLM_MODEL
S=/private/tmp/claude-501/-Users-yaliandrona/0caf6bfb-ebc7-450c-98aa-62f983fd7244/scratchpad
for target in 1 2 3; do
  export AGR_TARGET_SAMPLES=$target
  export AGR_SAMPLES=$target   # write indices 0..target-1; existing ones are skipped
  for pass in 1 2 3 4 5 6 7 8; do
    uv run python scripts/recording_gap.py > $S/todo.txt
    n=$(wc -l < $S/todo.txt | tr -d ' ')
    echo "=== target n=$target pass $pass: $n graphs remaining ===" >> $S/record.log
    [ "$n" -eq 0 ] && break
    while read -r g; do
      [ -z "$g" ] && continue
      uv run python scripts/record_live.py "$g" >> $S/record.log 2>&1
    done < $S/todo.txt
  done
done
echo "DONE" >> $S/record.log
