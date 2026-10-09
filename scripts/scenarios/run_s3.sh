#!/bin/bash
# run_s3.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane>
# S3 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §7.5):
# SC-COMMON-01 prefix; SC-S3-01 (the saved model's size as an auxiliary metric: the fictional user changes its input
# unit in research-tree.yaml — re-evaluating the imported runs is refused — restores it and changes only its canonical
# unit with an equivalent bound, then tries to change the frozen primary metric's canonical unit); SC-S3-02 (incomplete
# copies of a real run's manifest in fault-injection/ are refused with nothing written, the original imports, a
# restart keeps the units and the reasons); SC-COMMON-01 suffix. SC-S3-03 (an old project upgraded) is
# run_s3_upgrade.sh. Checkpoints after every step; panes closed and the build packed at the end.
set -u
confirm_exit() {  # Claude Code asks before stopping running background tasks: confirm, or the old session stays
  sleep 4
  if herdr pane read $pane 2>/dev/null | tail -15 | grep -q "Exit and stop tasks"; then
    herdr pane send-keys $pane Enter >/dev/null 2>&1
    echo '{"event":"confirmed the Claude Code exit dialog (background tasks were running)"}' >> $C/commands.jsonl; sleep 3
  fi
}
host=$1; att=$2; pane=$3; spane=$4
R=/home/yu/workspace/rt-scenarios; S=$R/S3; REPO=/home/yu/workspace/research-tree
mkdir -p $S
P=$S/rt-S3-$host-a$att; C=$P.ctl; A=s3${host:0:2}$att
cd $REPO
[ -e $P ] && { echo "$P exists"; exit 2; }
python3 scripts/make_rt_test_project.py $P --host $host --stage S3 --case SC-S3 --attempt $((10#$att)) \
  --hypothesis-title "Zebra：重球动量在固定更新预算下收敛更快" >/dev/null || exit 2
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
rm -rf $S/dist-$host-S3a$att; cp -r dist/$host $S/dist-$host-S3a$att
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
cp $REPO/scripts/scenarios/s3_fault_plan.json $C/fault-plan.json
herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
herdr pane run $spane "cd $P && python3 tools/local_exec.py serve"
herdr pane run $pane "cd $P"; sleep 2
start_agent() {
  if [ $host = claude ]; then
    herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S3a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
    sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
  else
    herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
  fi
}
if [ $host = claude ]; then CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else
  sh scripts/setup_codex_home.sh $S/codex-home-S3a$att $P $S/dist-codex-S3a$att >/dev/null 2>&1
  herdr pane run $pane "export CODEX_HOME=$S/codex-home-S3a$att"; sleep 1
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
  $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $P --tools $S/dist-$host-S3a$att/plugins/research-tree/tools --out $C/checkpoint-$1.json >/dev/null 2>&1
  $REPO/.venv/bin/python - "$P" "$S/dist-$host-S3a$att/plugins/research-tree/tools" "$C/usage-$1.json" <<'PY' >/dev/null 2>&1
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
say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；主指标 accuracy，辅助指标 model_bytes（保存的模型文件大小，按配置里的指标规范）；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。完成立项计划并请我确认。" 5400
say "$CMD confirm" 5400
for i in $(seq 1 24); do ck progress >/dev/null; n=$(python3 -c "import json; d=json.load(open('$C/checkpoint-progress.json')); print(1 if any(e['kind']=='baseline' and e.get('evaluation_id') for e in d['experiments']) else 0)" 2>/dev/null); echo "[$(date +%T)] baseline evaluated: $n"; [ "${n:-0}" = 1 ] && break; wait_agent 1800; say "继续推进根节点：框架 sanity、冻结、参考方法三个 seed 的基线（探索集 explore）、评估并设为 SOTA；完成后告诉我。" 3600; done
ck A-sota
say "在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写方法配置文件 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交；在 Zebra 上用 config_path 登记这个方法实验，按规则做 sanity、代码审查、三个搜索 seed 的运行、导入与评估。告诉我 accuracy 与 model_bytes 的评估结果（含保护指标是否通过）。" 5400
ck B-zebra
python3 $REPO/scripts/scenarios/s3_edit_config.py $P/research-tree.yaml input-mib
echo '{"event":"fictional user edited research-tree.yaml: model_bytes input_unit bytes -> mib (F-S3-01)"}' >> $C/commands.jsonl
say "我把 research-tree.yaml 里 model_bytes 的 input_unit 改成了 mib。请按流程让这个配置生效（需要的话用 $CMD config apply，指标规范变化按规则登记），然后重新评估 SOTA 与 Zebra 的实验；不要重新训练，如实告诉我接口的回答。" 3600
ck C-input-unit-changed
python3 $REPO/scripts/scenarios/s3_edit_config.py $P/research-tree.yaml canonical-mib
echo '{"event":"fictional user edited research-tree.yaml: model_bytes input_unit back to bytes, canonical_unit bytes -> mib, allowed_regression 1024 bytes -> 0.0009765625 MiB (the same bound)"}' >> $C/commands.jsonl
say "我把 model_bytes 的 input_unit 恢复成 bytes，只把比较单位 canonical_unit 改成 mib，并把允许的退化换算成等价的 0.0009765625 MiB（= 1024 字节）。请让配置生效、按规则登记，然后重新评估 SOTA 与 Zebra；告诉我 model_bytes 的效应与保护判定和之前是否一致。不要重新训练。" 3600
ck D-canonical-changed
python3 $REPO/scripts/scenarios/s3_edit_config.py $P/research-tree.yaml primary-fraction
echo '{"event":"fictional user edited research-tree.yaml: accuracy canonical_unit percentage_point -> fraction (the frozen primary metric)"}' >> $C/commands.jsonl
say "我又把主指标 accuracy 的 canonical_unit 改成了 fraction。请尝试让它生效并如实告诉我结果；如果被拒，就把 research-tree.yaml 里的这一项改回 percentage_point（这一处你可以替我改回），保持原来的规范。" 2400
ck E-primary-refused
say "请在 Zebra 上登记一个新的方法实验：在 zebra/ 目录写 zebra/m3.json（momentum，lr 0.01，beta 0.9，其余同参考方法）并提交，用 config_path 登记，按规则做 sanity 与代码审查，然后只运行 seed 42 到训练完成（succeeded），先不要导入。告诉我这个 run 的 manifest 路径。" 5400
ck F-run-not-imported
$REPO/.venv/bin/python $REPO/scripts/scenarios/s3_fault_copies.py $C $P $S/dist-$host-S3a$att/plugins/research-tree/tools >/dev/null
python3 -c 'import json,sys; print(json.dumps({"event": "controller made fault-injection copies (F-S3-02)", "record": json.load(open(sys.argv[1]))}))' $C/fault-applied.json >> $C/commands.jsonl
say "研究目录 fault-injection/ 里有两份那个 run 的 manifest 副本（一份缺 train_seed，一份缺 units）。请先分别用这两份副本尝试 import_run_result，如实告诉我接口的回答和数据库里这个 run 是否有任何导入记录；然后再用原始 manifest 导入。" 2400
ck G-copies-refused
end_session "after the fault-injection imports"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，再告诉我 Zebra 那个 lr 0.01 run 的导入记录里的原始单位，以及刚才两份副本为什么被拒（从你能查到的记录核对）。只核对，不启动新实验。" 2400
ck H-after-restart
say "$CMD build" 900; say "$CMD check" 900
ck final
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
mkdir -p $C/sessions
if [ $host = claude ]; then cp ~/.claude/projects/$(echo $P | sed 's|/|-|g')/*.jsonl $C/sessions/ 2>/dev/null
else find $S/codex-home-S3a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null; fi
cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state
$REPO/.venv/bin/python -c "
import sys,json,glob; sys.path.insert(0,'$S/dist-$host-S3a$att/plugins/research-tree/tools')
from research_db import ResearchDB
db=glob.glob('$P/research/*/research_tree.db')[0]
json.dump(ResearchDB(db,'ui/ui').export_snapshot(), open('$C/db-snapshot-final.json','w'), ensure_ascii=False, default=str)"
for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
[ $host = codex ] && rm -f $S/codex-home-S3a$att/auth.json
# this attempt's build is packed away, so a later attempt's agent cannot find and run an older plugin
mkdir -p $R/archive && tar -czf $R/archive/build-S3-$host-a$att.tar.gz -C $S dist-$host-S3a$att $( [ $host = codex ] && echo codex-home-S3a$att ) 2>/dev/null \
  && rm -rf $S/dist-$host-S3a$att $( [ $host = codex ] && echo $S/codex-home-S3a$att )
echo "[$(date +%T)] done (panes closed)"
