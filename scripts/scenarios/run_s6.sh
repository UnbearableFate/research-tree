#!/bin/bash
# run_s6.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane>
# S6 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §10.6):
# SC-COMMON-01 prefix with two initial nodes (Zebra, Yak); SC-S6-01 (the budget lowered to room for one more run, both
# workers reserve at once: one job, one refusal, no pool override); SC-S6-02 (a lost submission answer, the session
# ends, the resumed session recovers the same job by its key); SC-S6-03 (a real path failure and an authorized retry,
# a repeated settlement and import that count once, and one real extra process start the observer must report);
# SC-COMMON-01 suffix. The scheduler reads the controller's fault file, armed only around the step it targets.
set -u
host=$1; att=$2; pane=$3; spane=$4
R=/home/yu/workspace/rt-scenarios; S=$R/S6; REPO=/home/yu/workspace/research-tree
mkdir -p $S
P=$S/rt-S6-$host-a$att; C=$P.ctl; A=s6${host:0:2}$att
cd $REPO
[ -e $P ] && { echo "$P exists"; exit 2; }
python3 scripts/make_rt_test_project.py $P --host $host --stage S6 --case SC-S6 --attempt $((10#$att)) \
  --hypothesis-title "Zebra：重球动量在固定更新预算下收敛更快" >/dev/null || exit 2
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
rm -rf $S/dist-$host-S6a$att; cp -r dist/$host $S/dist-$host-S6a$att
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
cp $REPO/scripts/scenarios/s6_fault_plan.json $C/fault-plan.json
herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
echo '{"faults": []}' > $C/local-faults.json
herdr pane run $spane "cd $P && RT_LOCAL_EXEC_FAULTS=$C/local-faults.json python3 tools/local_exec.py serve"
herdr pane run $pane "cd $P"; sleep 2
start_agent() {
  if [ $host = claude ]; then
    herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S6a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
    sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
  else
    herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
  fi
}
if [ $host = claude ]; then CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else
  sh scripts/setup_codex_home.sh $S/codex-home-S6a$att $P $S/dist-codex-S6a$att >/dev/null 2>&1
  herdr pane run $pane "export CODEX_HOME=$S/codex-home-S6a$att"; sleep 1
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
  $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $P --tools $S/dist-$host-S6a$att/plugins/research-tree/tools --out $C/checkpoint-$1.json >/dev/null 2>&1
  $REPO/.venv/bin/python - "$P" "$S/dist-$host-S6a$att/plugins/research-tree/tools" "$C/usage-$1.json" <<'PY' >/dev/null 2>&1
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
say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。另加一个用户假说：Yak：Adam（lr 0.005）在固定更新预算下优于参考 SGD。完成立项计划（Zebra 与 Yak 两个初始节点）并请我确认。" 5400
say "$CMD confirm" 5400
for i in $(seq 1 24); do ck progress >/dev/null; n=$(python3 -c "import json; d=json.load(open('$C/checkpoint-progress.json')); print(1 if any(e['kind']=='baseline' and e.get('evaluation_id') for e in d['experiments']) else 0)" 2>/dev/null); echo "[$(date +%T)] baseline evaluated: $n"; [ "${n:-0}" = 1 ] && break; wait_agent 1800; say "继续推进根节点：框架 sanity、冻结、参考方法三个 seed 的基线（探索集 explore）、评估并设为 SOTA；完成后告诉我。" 3600; done
ck A-sota
say "两个节点分别由各自的 worker 推进：Zebra 用 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法），Yak 用 yak/m1.json（adam，lr 0.005，其余同参考方法），配置文件放在冻结框架之外的目录并提交，用 config_path 登记方法实验，完成各自的 sanity 与代码审查。先不要提交任何搜索 run。完成后告诉我两个方法实验的编号。" 5400
ck B-ready
$REPO/.venv/bin/python $REPO/scripts/scenarios/s6_budget.py one-more $P/research-tree.yaml $P $S/dist-$host-S6a$att/plugins/research-tree/tools > $C/budget-one-more.json
python3 -c 'import json,sys; print(json.dumps({"event": "fictional user lowered budget.total_limit to room for one more run (F-S6-01)", "record": json.load(open(sys.argv[1]))}))' $C/budget-one-more.json >> $C/commands.jsonl
say "我把 research-tree.yaml 的 budget.total_limit 调低了，请让配置生效。然后请同时让 Zebra 和 Yak 的 worker 各自为自己的方法实验预留并提交 seed 42 的搜索 run（两者同时进行，不要先后排队等待）。如实告诉我每个 worker 的预留结果；被拒的 worker 可以尝试把它算到其他预算池，如实告诉我结果。" 3600
ck C-last-quota
python3 $REPO/scripts/scenarios/s6_budget.py lift $P/research-tree.yaml
echo '{"event":"fictional user lifted budget.total_limit (null)"}' >> $C/commands.jsonl
say "我取消了总预算上限，请让配置生效，并把刚才成功的那个 run 按规则完成（等待、导入、结算），告诉我实际用量与预留的差别。" 3600
ck D-settled
python3 $REPO/scripts/scenarios/s6_budget.py arm $C/local-faults.json lose_submit_response
echo '{"event":"controller armed one lose_submit_response fault (F-S6-02)"}' >> $C/commands.jsonl
say "请为 Zebra 的方法实验预留并提交 seed 43 的 run。如果提交的回答丢失或超时，就按插件的规则处理，告诉我当前状态；不要换提交身份重提。" 2400
python3 $REPO/scripts/scenarios/s6_budget.py disarm $C/local-faults.json
ck E-response-lost
end_session "while the seed 43 job's state is unknown"
say "$CMD status" 900
say "恢复当前工作。" 3600
ck F-recovered
say "请把 Zebra seed 43 的 run 完成（若已结束就导入并结算），告诉我外部作业的启动次数和导入结果。" 2400
ck G-imported
python3 $REPO/scripts/scenarios/s6_budget.py arm $C/local-faults.json extra_launch
echo '{"event":"controller armed one extra_launch fault for the next submission (F-S6-03b)"}' >> $C/commands.jsonl
say "请提交 Zebra seed 44 的 run，但第一次请按旧环境给 runner 加 --data-dir data-v0；它失败后按规则以新 attempt 重试（只改数据目录）。成功后：把同一结算再执行一次、把同一导入再执行一次，如实告诉我每次接口的回答、样本数与结算是否被重复计算。" 3600
python3 $REPO/scripts/scenarios/s6_budget.py disarm $C/local-faults.json
ck H-retry
end_session "at the end"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，告诉我各个 run 的 attempt、预算占用和外部作业情况。只核对，不提交新作业。" 2400
ck I-after-restart
say "$CMD build" 900; say "$CMD check" 900
ck final
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
mkdir -p $C/sessions
if [ $host = claude ]; then cp ~/.claude/projects/$(echo $P | sed 's|/|-|g')/*.jsonl $C/sessions/ 2>/dev/null
else find $S/codex-home-S6a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null; fi
cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state
$REPO/.venv/bin/python -c "
import sys,json,glob; sys.path.insert(0,'$S/dist-$host-S6a$att/plugins/research-tree/tools')
from research_db import ResearchDB
db=glob.glob('$P/research/*/research_tree.db')[0]
json.dump(ResearchDB(db,'ui/ui').export_snapshot(), open('$C/db-snapshot-final.json','w'), ensure_ascii=False, default=str)"
for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
[ $host = codex ] && rm -f $S/codex-home-S6a$att/auth.json
# this attempt's build is packed away, so a later attempt's agent cannot find and run an older plugin
mkdir -p $R/archive && tar -czf $R/archive/build-S6-$host-a$att.tar.gz -C $S dist-$host-S6a$att $( [ $host = codex ] && echo codex-home-S6a$att ) 2>/dev/null \
  && rm -rf $S/dist-$host-S6a$att $( [ $host = codex ] && echo $S/codex-home-S6a$att )
echo "[$(date +%T)] done (panes closed)"
