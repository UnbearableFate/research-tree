#!/bin/bash
# scenario.sh <stage S2..S7> <host claude|codex> <two-digit attempt> <agent-pane> <scheduler-pane>
# One stage's real scenarios on one project: the opening (SC-COMMON-01's prefix), the stage body (sN.sh), the common
# end. Variants (see lib.sh): FORK=<rt-scenarios/<stage>/prefix-<host>-aNN.tar.gz> starts from a saved opening;
# SMOKE=1 checks the controller's plumbing without an agent (scripts/scenarios/smoke.sh).
set -u
[ $# = 5 ] || { sed -n '2,5p' "$0"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
[ -f $HERE/s${1#S}.sh ] || { echo "no stage body s${1#S}.sh"; exit 2; }
source $HERE/lib.sh
source $HERE/s${STAGE#S}.sh
start_scheduler; open_shell; start_agent
if [ -z "$FORK" ]; then
  echo "[$(date +%T)] prepare"; say "$CMD prepare" 900
  echo "[$(date +%T)] init"; say "$CMD init" 5400
  decision
  say "$CMD confirm" 5400
  baseline_loop
  ck A-sota
  save_prefix
else
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，再告诉我根节点的基线、SOTA 和 Zebra 节点的状态。只核对，不启动新实验。" 2400
  ck A-forked
fi
body
say "$CMD build" 900; say "$CMD check" 900
ck final
finish
