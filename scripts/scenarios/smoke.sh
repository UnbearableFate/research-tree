#!/bin/bash
# smoke.sh <stage S2..S7> [host claude|codex]  — the controller's plumbing in minutes, never evidence.
# Runs scenario.sh with SMOKE=1 on a freshly generated project under rt-scenarios/smoke/: no agent and no herdr pane
# (both are logging stubs), so every prompt is only logged, every checkpoint and helper runs against the opening
# project, and a helper that exits non-zero, a checkpoint the observer could not take or a bash error shows up.
# It then lists prompt paths that point into the frozen harness (code/toytrain, code/configs, code/data), where a
# method file must not be written. What the agent would do is not checked at all.
# On a fresh project there is no database (no agent ran init), so checkpoints are skipped and database helpers fail;
# with FORK=<rt-scenarios/<stage>/prefix-<host>-aNN.tar.gz> in the environment the stage body's helpers and
# checkpoints run against a real saved opening (inside bwrap, like a real fork).
set -u
stage=$1; host=${2:-claude}; HERE=$(cd "$(dirname "$0")" && pwd)
R=/home/yu/workspace/rt-scenarios/smoke/$stage; mkdir -p $R
att=$(printf %02d $(( $(ls -d $R/rt-$stage-$host-a* 2>/dev/null | wc -l) + 1 )))
log=$R/smoke-$host-a$att.log
SMOKE=1 bash $HERE/scenario.sh $stage $host $att - - > $log 2>&1; rc=$?
C=$R/rt-$stage-$host-a$att.ctl
echo "smoke $stage $host a$att: controller exit $rc (log $log)"
grep -E "line [0-9]+:|command not found|No such file|Traceback|syntax error" $log | sed 's/^/  ERROR /'
grep -h '"event":"helper exited\|observer failed' $C/commands.jsonl 2>/dev/null | sed 's/^/  ERROR /'
echo "  prompts: $(grep -c smoke_prompt $C/commands.jsonl 2>/dev/null); checkpoints: $(ls $C/checkpoint-*.json 2>/dev/null | wc -l)"
python3 - $C/commands.jsonl <<'PY'
import json, re, sys
for line in open(sys.argv[1], encoding="utf-8"):
    text = json.loads(line).get("smoke_prompt") or ""
    for path in re.findall(r"(?:code/)?(?:toytrain|configs|data)/[\w./-]+\.(?:json|py|yaml)", text):
        print(f"  WARN prompt names a file in the frozen harness: {path} — {text[:80]}")
PY
[ $rc = 0 ] && ! grep -qE "line [0-9]+:|command not found|Traceback|syntax error" $log
