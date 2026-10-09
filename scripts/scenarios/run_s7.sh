#!/bin/bash
# run_s7.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane>
# S7 functional real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md
# §11.7): SC-COMMON-01 prefix with two nodes (Zebra, Yak); SC-S7-01 (real paired noise and the protocol's bounded
# repetition advice followed until it stops or its seed pool is used up; never the confirmation pool; a restart agrees
# with the completed runs); SC-S7-02 (a combination node over parents with limited or unclear gains, its choice tied
# to named findings; no gain is kept as it is); SC-COMMON-01 suffix. SC-S7-03 (the matched pilot) is separate.
set -u
host=$1; att=$2; pane=$3; spane=$4
R=/home/yu/workspace/rt-scenarios; S=$R/S7; REPO=/home/yu/workspace/research-tree
mkdir -p $S
P=$S/rt-S7-$host-a$att; C=$P.ctl; A=s7${host:0:2}$att
cd $REPO
[ -e $P ] && { echo "$P exists"; exit 2; }
python3 scripts/make_rt_test_project.py $P --host $host --stage S7 --case SC-S7 --attempt $((10#$att)) \
  --hypothesis-title "Zebra：重球动量在固定更新预算下收敛更快" >/dev/null || exit 2
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
rm -rf $S/dist-$host-S7a$att; cp -r dist/$host $S/dist-$host-S7a$att
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
cp $REPO/scripts/scenarios/s7_fault_plan.json $C/fault-plan.json
herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
herdr pane run $spane "cd $P && python3 tools/local_exec.py serve"
herdr pane run $pane "cd $P"; sleep 2
start_agent() {
  if [ $host = claude ]; then
    herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S7a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
    sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
  else
    herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
  fi
}
if [ $host = claude ]; then CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else
  sh scripts/setup_codex_home.sh $S/codex-home-S7a$att $P $S/dist-codex-S7a$att >/dev/null 2>&1
  herdr pane run $pane "export CODEX_HOME=$S/codex-home-S7a$att"; sleep 1
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
    if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
    sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
    for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
    exit 3
  fi
}
ck() {  # read-only checkpoint (observer) and the material-usage record
  $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $P --tools $S/dist-$host-S7a$att/plugins/research-tree/tools --out $C/checkpoint-$1.json >/dev/null 2>&1
  $REPO/.venv/bin/python - "$P" "$S/dist-$host-S7a$att/plugins/research-tree/tools" "$C/usage-$1.json" <<'PY' >/dev/null 2>&1
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
  if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
  sleep 6; A=${A}r; start_agent
}
echo "[$(date +%T)] prepare"; say "$CMD prepare" 900
echo "[$(date +%T)] init"; say "$CMD init" 5400
say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。另加一个用户假说：Yak：学习率在一轮内余弦衰减（其余同参考方法）在固定更新预算下优于参考 SGD。完成立项计划（Zebra 与 Yak 两个初始节点）并请我确认。" 5400
say "$CMD confirm" 5400
for i in $(seq 1 24); do ck progress >/dev/null; n=$(python3 -c "import json; d=json.load(open('$C/checkpoint-progress.json')); print(1 if any(e['kind']=='baseline' and e.get('evaluation_id') for e in d['experiments']) else 0)" 2>/dev/null); echo "[$(date +%T)] baseline evaluated: $n"; [ "${n:-0}" = 1 ] && break; wait_agent 1800; say "继续推进根节点：框架 sanity、冻结、参考方法三个 seed 的基线（探索集 explore）、评估并设为 SOTA；完成后告诉我。" 3600; done
ck A-sota
say "请推进 Zebra：在冻结框架之外的 zebra/ 目录写 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交，用 config_path 登记方法实验，完成 sanity、代码审查、三个搜索 seed 的运行、导入与评估。然后调用 repetition_advice，告诉我它的输入（配对差值、独立单元）、建议与理由。" 5400
ck B-zebra-advice
say "请按 repetition_advice 的建议行事：若建议追加重复，就在协议声明的 seed 池里按建议追加并通过正常预算预留运行、导入、重新评估，再问一次建议；一直到建议不再追加或 seed 池用完为止。不要使用确认材料或确认 seed。告诉我每一轮的建议与最终结论。" 7200
ck C-repeats
end_session "after the repetition rounds"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，再问一次 Zebra 的 repetition_advice，告诉我它与已完成的 run 是否一致。只核对，不启动新实验。" 2400
ck D-after-restart
say "请推进 Yak：在 yak/ 目录写 yak/m1.json（实现一轮内的余弦学习率衰减；如 runner 不支持就在 Yak 的工作树里实现这个选项并提交，其余同参考方法），完成 sanity、代码审查、三个搜索 seed 的运行、导入与评估。然后分别为 Zebra 与 Yak 写研究发现（finding），并在本批次的决定文档里用 note_findings 登记这批新发现（列出 finding 文档）。告诉我两者的结论。" 7200
ck E-yak
say "两个机制单独的收益有限或不确定。请按规则建立一个组合节点：用 relations 的 combines 关系引用 Zebra 与 Yak，说明它要区分的解释、所依据的 finding、什么结果会改变下一步与成本；实现同时启用动量与余弦衰减的配置并做最小对照（与两个父节点同 seed），按规则运行、导入、评估。结果没有收益就如实保留，不要改指标或父节点状态。告诉我组合节点的结论与它和父节点的关系。" 7200
ck F-combination
end_session "at the end"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，告诉我三个节点的状态、关系与停滞计数。只核对。" 2400
ck G-after-restart
say "$CMD build" 900; say "$CMD check" 900
ck final
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
mkdir -p $C/sessions
if [ $host = claude ]; then cp ~/.claude/projects/$(echo $P | sed 's|/|-|g')/*.jsonl $C/sessions/ 2>/dev/null
else find $S/codex-home-S7a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null; fi
cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state
$REPO/.venv/bin/python -c "
import sys,json,glob; sys.path.insert(0,'$S/dist-$host-S7a$att/plugins/research-tree/tools')
from research_db import ResearchDB
db=glob.glob('$P/research/*/research_tree.db')[0]
json.dump(ResearchDB(db,'ui/ui').export_snapshot(), open('$C/db-snapshot-final.json','w'), ensure_ascii=False, default=str)"
for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
[ $host = codex ] && rm -f $S/codex-home-S7a$att/auth.json
# this attempt's build is packed away, so a later attempt's agent cannot find and run an older plugin
mkdir -p $R/archive && tar -czf $R/archive/build-S7-$host-a$att.tar.gz -C $S dist-$host-S7a$att $( [ $host = codex ] && echo codex-home-S7a$att ) 2>/dev/null \
  && rm -rf $S/dist-$host-S7a$att $( [ $host = codex ] && echo $S/codex-home-S7a$att )
echo "[$(date +%T)] done (panes closed)"
