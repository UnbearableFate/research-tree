#!/bin/bash
# lib.sh — shared machinery of the stage scenario controllers (scripts/scenarios/sN.sh, run with scenario.sh).
#
#   bash scripts/scenarios/scenario.sh <stage S2..S7> <host claude|codex> <attempt> <agent-pane> <scheduler-pane>
#   FORK=<prefix snapshot .tar.gz> bash scripts/scenarios/scenario.sh ...   # retry from a saved prefix
#   SMOKE=1 bash scripts/scenarios/scenario.sh <stage> <host> <attempt> - -  # plumbing check, no agent, no panes
#
# A full run generates a fresh ToyOpt Lab project, runs the stage's prefix (prepare, init, the user's decisions,
# confirm, the root baseline: SC-COMMON-01's opening), saves the project as a prefix snapshot
# (rt-scenarios/<stage>/prefix-<host>-aNN.tar.gz) and runs the stage body and the common suffix.
# A fork (FORK=...) unpacks a snapshot into its own attempt directory and runs the agent, its scheduler and every
# controller-side read inside bwrap with that copy bound at the snapshot's original path (the database, the marker
# and the worktrees name absolute paths), starting a new host session — a resume — and then the stage body. The
# prefix's checkpoints are copied into the attempt with forked_from.json, so a record says where its opening came
# from. Forks of one snapshot run one at a time (they share the original path's host transcript folder).
# SMOKE=1 replaces the agent and herdr with logging stubs: the controller's flow, its helpers and the record
# script run on a freshly generated project in minutes. A smoke run is never evidence.
set -u
STAGE=$1; host=$2; att=$3; pane=$4; spane=$5
R=/home/yu/workspace/rt-scenarios; REPO=/home/yu/workspace/research-tree
SMOKE=${SMOKE:-0}; FORK=${FORK:-}
S=$R/$STAGE; [ $SMOKE = 1 ] && S=$R/smoke/$STAGE   # smoke projects never sit beside real attempts
ARCH=$R/archive; [ $SMOKE = 1 ] && ARCH=$S/archive   # a smoke run never touches the real archives
mkdir -p $S $ARCH
P=$S/rt-$STAGE-$host-a$att; C=$P.ctl; A=${STAGE,,}${host:0:2}$att
cd $REPO
[ -e $P ] && { echo "$P exists"; exit 2; }
RUN=""                      # prefix for every command that must see the project at its recorded path
PV=$P                       # the project path as the project's own records name it
if [ $SMOKE = 1 ]; then
  herdr() { echo "herdr $*" >> $C/smoke-herdr.log; [ "${1:-}" = agent ] && [ "${2:-}" = get ] && echo '{"result":{"agent":{"agent_status":"idle"}}}'; return 0; }
fi

# ---------------------------------------------------------------------------------------------- project and build
if [ -n "$FORK" ]; then
  mkdir -p $P $C
  tar -xzf "$FORK" -C $P --strip-components=1 || exit 2
  PV=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project"])' "${FORK%.tar.gz}.json")
  RUN="bwrap --dev-bind / / --bind $P $PV --chdir $PV"
  cp "${FORK%.tar.gz}.json" $C/forked_from.json
  O=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["ctl"])' "${FORK%.tar.gz}.json")
  for f in checkpoint-A-sota.json usage-A-sota.json; do cp $O/$f $C/prefix-$f 2>/dev/null; done  # the opening's evidence
  [ -d $PV ] || mkdir -p $PV   # the bind target (the original attempt may be archived)
  echo "{\"event\":\"forked from the prefix snapshot $(basename $FORK) (opening steps of $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["attempt"])' "${FORK%.tar.gz}.json")); the project is shown at $PV through bwrap\"}" >> $C/commands.jsonl
else
  python3 scripts/make_rt_test_project.py $P --host $host --stage $STAGE --case SC-$STAGE --attempt $((10#$att)) \
    --hypothesis-title "Zebra：重球动量在固定更新预算下收敛更快" >/dev/null || exit 2
fi
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
DIST=$S/dist-$host-${STAGE}a$att
rm -rf $DIST; cp -r dist/$host $DIST
TOOLS=$DIST/plugins/research-tree/tools
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
cp $REPO/scripts/scenarios/${STAGE,,}_fault_plan.json $C/fault-plan.json 2>/dev/null
[ -f $C/local-faults.json ] || echo '{"faults": []}' > $C/local-faults.json

# ---------------------------------------------------------------------------------------------- host plumbing
confirm_exit() {  # Claude Code asks before stopping running background tasks: confirm, or the old session stays
  sleep 4
  if herdr pane read $pane 2>/dev/null | tail -15 | grep -q "Exit and stop tasks"; then
    herdr pane send-keys $pane Enter >/dev/null 2>&1
    echo '{"event":"confirmed the Claude Code exit dialog (background tasks were running)"}' >> $C/commands.jsonl; sleep 3
  fi
}
start_scheduler() {
  herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
  herdr pane run $spane "cd $PV 2>/dev/null; RT_LOCAL_EXEC_FAULTS=$C/local-faults.json $RUN python3 tools/local_exec.py serve"
}
start_agent() {
  if [ $SMOKE = 1 ]; then echo "{\"smoke\":\"start $A\"}" >> $C/commands.jsonl; return; fi
  if [ $host = claude ]; then
    herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $DIST/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
    sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
  else
    herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
  fi
}
quit_agent() {
  if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
}
open_shell() {  # the agent pane's shell: inside bwrap for a fork; Codex gets its isolated home
  [ -n "$RUN" ] && { herdr pane run $pane "$RUN bash"; sleep 2; }
  herdr pane run $pane "cd $PV"; sleep 1
  if [ $host = codex ]; then
    sh scripts/setup_codex_home.sh $S/codex-home-${STAGE}a$att $PV $DIST >/dev/null 2>&1
    herdr pane run $pane "export CODEX_HOME=$S/codex-home-${STAGE}a$att"; sleep 1
  fi
}
if [ $host = claude ]; then CMD=/research-tree; wait_agent() { [ $SMOKE = 1 ] || $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else CMD='$research-tree'; wait_agent() { [ $SMOKE = 1 ] || $R/drive_codex.sh $A $pane $C ${1:-3600} >/dev/null; }
fi
limit_hit() {  # the host's account limit is an environment block, never an agent answer
  [ $SMOKE = 1 ] && return 1
  herdr pane read $pane 2>/dev/null | tail -60 | grep -qiE "hit your (session|usage|weekly) limit|usage limit reached|You've hit your usage limit"
}
say() {
  if [ $SMOKE = 1 ]; then
    python3 -c 'import json,sys; print(json.dumps({"smoke_prompt": sys.argv[1]}, ensure_ascii=False))' "$1" >> $C/commands.jsonl; return
  fi
  $R/say.sh $C $A 120000 "$1" >/dev/null 2>&1; sleep 5; wait_agent ${2:-3600}
  if [ "$(herdr agent get $A 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['agent']['agent_status'])" 2>/dev/null)" = blocked ]; then
    herdr pane read $pane 2>/dev/null | tail -30 > $C/question-$(date +%H%M%S).txt
    echo '{"event":"the agent asked the user a question (saved beside this log); the controller dismissed it"}' >> $C/commands.jsonl
    herdr agent send-keys $A Escape >/dev/null 2>&1; sleep 3
  fi
  if limit_hit; then
    echo '{"event":"BLOCKED: the host reported its usage limit; the attempt stops here"}' >> $C/commands.jsonl
    echo "[$(date +%T)] BLOCKED: host usage limit"; ck blocked-usage-limit; quit_agent; finish; exit 3
  fi
}
ck() {  # read-only checkpoint: the observer and the material-usage record
  if [ $SMOKE = 1 ] && ! ls $P/research/*/research_tree.db >/dev/null 2>&1; then
    echo "{\"smoke\":\"checkpoint $1 skipped: no database yet (no agent ran init)\"}" >> $C/commands.jsonl; return; fi
  $RUN $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $PV --tools $TOOLS --out $C/checkpoint-$1.json >/dev/null 2>&1 \
    || echo "{\"event\":\"checkpoint $1: the observer failed\"}" >> $C/commands.jsonl
  $RUN $REPO/.venv/bin/python $REPO/scripts/scenarios/usage_snapshot.py "$PV" "$TOOLS" "$C/usage-$1.json" >/dev/null 2>&1
  echo "[$(date +%T)] checkpoint $1"
}
helper() {  # a controller helper that reads or edits the project: run where the project is visible at its path
  $RUN "$@"; local rc=$?
  [ $rc = 0 ] || echo "{\"event\":\"helper exited $rc: $(basename ${2:-$1})\"}" >> $C/commands.jsonl
  return 0
}
end_session() {
  echo "{\"event\":\"end session ($1)\"}" >> $C/commands.jsonl
  quit_agent; sleep 2; A=${A}r; start_agent
}
baseline_loop() {  # until the root baseline is evaluated (the agent may stop to report on its way there)
  for i in $(seq 1 24); do
    ck progress >/dev/null
    n=$(python3 -c "import json; d=json.load(open('$C/checkpoint-progress.json')); print(1 if any(e['kind']=='baseline' and e.get('evaluation_id') for e in d['experiments']) else 0)" 2>/dev/null)
    echo "[$(date +%T)] baseline evaluated: ${n:-0}"; { [ "${n:-0}" = 1 ] || [ $SMOKE = 1 ]; } && break
    wait_agent 1800; say "继续推进根节点：框架 sanity、冻结、参考方法三个 seed 的基线（探索集 explore）、评估并设为 SOTA；完成后告诉我。" 3600
  done
}
save_prefix() {  # the project after the opening steps, for retries of the stage body
  [ $SMOKE = 1 ] && return
  local snap=$S/prefix-$host-a$att.tar.gz
  local outside=$(git -C $P/code worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' | grep -v "^$P/")
  if [ -n "$outside" ]; then  # a copy of the project would miss them: no faithful fork from this opening
    echo "{\"event\":\"prefix not saved: worktrees outside the project ($(echo $outside))\"}" >> $C/commands.jsonl
    echo "[$(date +%T)] prefix not saved (worktrees outside the project)"; return
  fi
  tar -czf $snap -C $S $(basename $P) && python3 -c 'import json,sys; json.dump({"project": sys.argv[1], "ctl": sys.argv[2], "attempt": sys.argv[3], "host": sys.argv[4], "stage": sys.argv[5], "snapshot": sys.argv[7]}, open(sys.argv[6], "w"))' \
    "$PV" "$C" "a$att" "$host" "$STAGE" "${snap%.tar.gz}.json" "$snap"
  echo "[$(date +%T)] prefix saved: $(basename $snap)"
}
finish() {  # build, check, final checkpoint, evidence, panes closed, build packed
  quit_agent; sleep 4; herdr pane send-keys $spane ctrl+c >/dev/null 2>&1
  mkdir -p $C/sessions
  if [ $SMOKE != 1 ]; then
    if [ $host = claude ]; then
      (cd ~/.claude/projects/$(echo $PV | sed 's|/|-|g') 2>/dev/null && find . -name "*.jsonl" -newer $C/source_ref.txt | cpio -pdm $C/sessions 2>/dev/null)
    else
      find $S/codex-home-${STAGE}a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; 2>/dev/null
      rm -f $S/codex-home-${STAGE}a$att/auth.json
    fi
  fi
  [ $host = codex ] && cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null
  cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state 2>/dev/null
  $RUN $REPO/.venv/bin/python $REPO/scripts/scenarios/db_snapshot.py "$PV" "$TOOLS" "$C/db-snapshot-final.json" >/dev/null 2>&1
  [ $SMOKE = 1 ] || for p in $pane $spane; do herdr pane close $p >/dev/null 2>&1; done
  tar -czf $ARCH/build-$STAGE-$host-a$att.tar.gz -C $S $(basename $DIST) $( [ $host = codex ] && [ -d $S/codex-home-${STAGE}a$att ] && echo codex-home-${STAGE}a$att ) 2>/dev/null \
    && rm -rf $DIST $S/codex-home-${STAGE}a$att
  echo "[$(date +%T)] done (panes closed)"
}
