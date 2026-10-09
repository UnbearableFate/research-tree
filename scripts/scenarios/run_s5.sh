#!/bin/bash
# run_s5.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane>
# S5 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §9.6):
# SC-COMMON-01 prefix; SC-S5-01 (a declared wrong data directory makes a real run fail; the agent freezes a check
# criterion, retries with the fix and registers a lesson whose fix is verified by the fixed checkers; a later run
# under the same conditions uses it); SC-S5-02 (control lessons resting on an unrelated run, on self-reported
# booleans, on a planned run; an unknown root cause with a verified fix; a restart changes none of them); SC-S5-03
# (a finding from a real evaluation; a protocol change; both packs and the resume package show it needing a recheck;
# a real re-check restores it); SC-COMMON-01 suffix. Checkpoints after every step; panes closed, build packed.
set -u
confirm_exit() {  # Claude Code asks before stopping running background tasks: confirm, or the old session stays
  sleep 4
  if herdr pane read $pane 2>/dev/null | tail -15 | grep -q "Exit and stop tasks"; then
    herdr pane send-keys $pane Enter >/dev/null 2>&1
    echo '{"event":"confirmed the Claude Code exit dialog (background tasks were running)"}' >> $C/commands.jsonl; sleep 3
  fi
}
host=$1; att=$2; pane=$3; spane=$4
R=/home/yu/workspace/rt-scenarios; S=$R/S5; REPO=/home/yu/workspace/research-tree
mkdir -p $S
P=$S/rt-S5-$host-a$att; C=$P.ctl; A=s5${host:0:2}$att
cd $REPO
[ -e $P ] && { echo "$P exists"; exit 2; }
python3 scripts/make_rt_test_project.py $P --host $host --stage S5 --case SC-S5 --attempt $((10#$att)) \
  --hypothesis-title "Zebra：重球动量在固定更新预算下收敛更快" >/dev/null || exit 2
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
rm -rf $S/dist-$host-S5a$att; cp -r dist/$host $S/dist-$host-S5a$att
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
cp $REPO/scripts/scenarios/s5_fault_plan.json $C/fault-plan.json
herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
herdr pane run $spane "cd $P && python3 tools/local_exec.py serve"
herdr pane run $pane "cd $P"; sleep 2
start_agent() {
  if [ $host = claude ]; then
    herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S5a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
    sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
  else
    herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
  fi
}
if [ $host = claude ]; then CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else
  sh scripts/setup_codex_home.sh $S/codex-home-S5a$att $P $S/dist-codex-S5a$att >/dev/null 2>&1
  herdr pane run $pane "export CODEX_HOME=$S/codex-home-S5a$att"; sleep 1
  CMD='$research-tree'; wait_agent() { $R/drive_codex.sh $A $pane $C ${1:-3600} >/dev/null; }
fi
start_agent
limit_hit() {  # the host's account limit is an environment block, never an agent answer: stop the attempt
  herdr pane read $pane 2>/dev/null | tail -60 | grep -qiE "hit your (session|usage|weekly) limit|usage limit reached|You've hit your usage limit"
}
say() {
  $R/say.sh $C $A 120000 "$1" >/dev/null 2>&1; sleep 5; wait_agent ${2:-3600}
  if [ "$(herdr agent get $A 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['agent']['agent_status'])" 2>/dev/null)" = blocked ]; then
    # the agent stopped at a question for the user: logged, dismissed; the next scripted message continues
    herdr pane read $pane 2>/dev/null | tail -30 > $C/question-$(date +%H%M%S).txt
    echo '{"event":"the agent asked the user a question (saved beside this log); the controller dismissed it"}' >> $C/commands.jsonl
    herdr agent send-keys $A Escape >/dev/null 2>&1; sleep 3
  fi
  if limit_hit; then
    echo '{"event":"BLOCKED: the host reported its usage limit; the attempt stops here"}' >> $C/commands.jsonl
    echo "[$(date +%T)] BLOCKED: host usage limit"; ck blocked-usage-limit
    if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
    sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
    for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
    exit 3
  fi
}
ck() {  # read-only checkpoint (observer) and the material-usage record
  $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $P --tools $S/dist-$host-S5a$att/plugins/research-tree/tools --out $C/checkpoint-$1.json >/dev/null 2>&1
  $REPO/.venv/bin/python - "$P" "$S/dist-$host-S5a$att/plugins/research-tree/tools" "$C/usage-$1.json" <<'PY' >/dev/null 2>&1
import glob, json, sys
sys.path.insert(0, sys.argv[2])
from research_db import ResearchDB
db = ResearchDB(glob.glob(f"{sys.argv[1]}/research/*/research_tree.db")[0], "ui/ui")
json.dump({"material_usage": db.material_usage(), "documents": [d for d in db.export_snapshot()["tables"]["document"]
           if d.get("doc_type") in ("candidate_spec", "confirmation_batch")]}, open(sys.argv[3], "w"), ensure_ascii=False, default=str)
PY
  echo "[$(date +%T)] checkpoint $1"
}
end_session() {
  echo "{\"event\":\"end session ($1)\"}" >> $C/commands.jsonl
  if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
  sleep 6; A=${A}r; start_agent
}
echo "[$(date +%T)] prepare"; say "$CMD prepare" 900
echo "[$(date +%T)] init"; say "$CMD init" 5400
say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。完成立项计划并请我确认。" 5400
say "$CMD confirm" 5400
for i in $(seq 1 24); do ck progress >/dev/null; n=$(python3 -c "import json; d=json.load(open('$C/checkpoint-progress.json')); print(1 if any(e['kind']=='baseline' and e.get('evaluation_id') for e in d['experiments']) else 0)" 2>/dev/null); echo "[$(date +%T)] baseline evaluated: $n"; [ "${n:-0}" = 1 ] && break; wait_agent 1800; say "继续推进根节点：框架 sanity、冻结、参考方法三个 seed 的基线（探索集 explore）、评估并设为 SOTA；完成后告诉我。" 3600; done
ck A-sota
say "在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写方法配置文件 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交，在 Zebra 上用 config_path 登记这个方法实验。按我们旧环境的习惯，第一次运行（方法的 sanity）请给 runner 加 --data-dir data-v0（旧环境的数据目录）。如实告诉我运行结果和日志里的错误。" 3600
ck B-failed
say "data-v0 是旧环境的目录，当前环境的数据在 code/data。请：1）先写一份验证用的任务请求（task_request），在其中的“## 检查项”JSON 块里冻结验收项（退出状态、导入有效、实际启动配置里的 data_dir、读入的评测样本数、产物与 manifest 一致）；2）再按规则以新 attempt 重试（只改数据目录）并导入、验收；3）然后把这次故障与修复登记为一条运行经验（lesson）：症状照日志写，根因如实写确定程度，修复是否已验证由 fix_verification 引用失败的 attempt、检查项文档、验证 attempt、实际修复与检查证据来说明。告诉我系统给出的经验状态（memory_status）。" 5400
ck C-lesson
say "再请登记两条对照经验，看看系统怎么判：一条引用另一个与这次修复无关的成功 run 作为验证；一条只在 front matter 里写 fix_applied: true、checks_passed: true 而不给 fix_verification。告诉我两条各自的 memory_status。不要删除它们。" 2400
ck D-controls
say "请再登记一个尚未执行的 run（在 Zebra 的方法实验上为 seed 43 create_run，但不要提交），并尝试用它作为一条 verified 经验的验证依据；告诉我接口或 memory_status 的结论。" 2400
ck E-unexecuted
end_session "after the lesson checks"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，读 context_pack，告诉我各条经验的声明状态、实际状态和根因确定程度。只核对。" 2400
ck F-after-restart
say "现在按规则把 Zebra 的方法实验走完：代码审查（若需要）与三个搜索 seed 的运行、导入与评估（运行时用正确的数据目录），参考已有的运行经验。完成后从这次评估写一条有范围的研究发现（finding），然后读 Leader 与 worker 两种 context_pack，告诉我这条发现的来源与支持状态。" 5400
ck G-finding
python3 $REPO/scripts/scenarios/s5_protocol_change.py $P/research-tree.yaml
echo '{"event":"fictional user edited research-tree.yaml: verification.max_confirmation_candidates 2 -> 1 (a protocol change, F-S5-03)"}' >> $C/commands.jsonl
say "我改了 research-tree.yaml 的验证设置（协议的一项）。请让配置生效、按规则登记新的协议版本，然后再读一次 Leader 与 worker 的 context_pack 和 Zebra 的恢复包，告诉我那条研究发现和各条运行经验现在的状态与原因。" 3600
ck H-protocol-changed
say "请在新协议下按规则补验：重新评估 Zebra（不重新训练；若协议要求更多证据就如实说明），必要时写新的研究发现，然后告诉我发现的当前状态。不要直接改任何文档的标签。" 3600
ck I-reverified
end_session "at the end"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，告诉我各条经验与研究发现的当前状态。只核对。" 2400
ck J-after-restart
say "$CMD build" 900; say "$CMD check" 900
ck final
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
mkdir -p $C/sessions
if [ $host = claude ]; then (cd ~/.claude/projects/$(echo $P | sed 's|/|-|g') && find . -name "*.jsonl" | cpio -pdm $C/sessions 2>/dev/null)
else find $S/codex-home-S5a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null; fi
cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state
$REPO/.venv/bin/python -c "
import sys,json,glob; sys.path.insert(0,'$S/dist-$host-S5a$att/plugins/research-tree/tools')
from research_db import ResearchDB
db=glob.glob('$P/research/*/research_tree.db')[0]
json.dump(ResearchDB(db,'ui/ui').export_snapshot(), open('$C/db-snapshot-final.json','w'), ensure_ascii=False, default=str)"
for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
[ $host = codex ] && rm -f $S/codex-home-S5a$att/auth.json
# this attempt's build is packed away, so a later attempt's agent cannot find and run an older plugin
mkdir -p $R/archive && tar -czf $R/archive/build-S5-$host-a$att.tar.gz -C $S dist-$host-S5a$att $( [ $host = codex ] && echo codex-home-S5a$att ) 2>/dev/null \
  && rm -rf $S/dist-$host-S5a$att $( [ $host = codex ] && echo $S/codex-home-S5a$att )
echo "[$(date +%T)] done (panes closed)"
