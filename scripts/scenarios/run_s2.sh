#!/bin/bash
# run_s2.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane>
# S2 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §6.5):
# SC-COMMON-01 prefix; a Zebra search and its rechecks; SC-S2-02 (a weak control offered as the confirmation
# reference); SC-S2-01 (frozen candidate, batch on c1, the reference re-run and the candidate's confirmation);
# SC-S2-04 (a declared input-path fault on one confirmation run, a session end while the material is in use, a
# repeated import, a valid result offered for re-running); SC-S2-03 (a retuned learning rate after the feedback:
# old spec, old batch, c1 and another node refused; a new candidate on c2); SC-COMMON-01 suffix. The controller only
# types what the fictional user says; after every step it keeps a read-only checkpoint. Panes are closed at the end.
set -u
confirm_exit() {  # Claude Code asks before stopping running background tasks: confirm, or the old session stays
  sleep 4
  if herdr pane read $pane 2>/dev/null | tail -15 | grep -q "Exit and stop tasks"; then
    herdr pane send-keys $pane Enter >/dev/null 2>&1
    echo '{"event":"confirmed the Claude Code exit dialog (background tasks were running)"}' >> $C/commands.jsonl; sleep 3
  fi
}
host=$1; att=$2; pane=$3; spane=$4
R=/home/yu/workspace/rt-scenarios; S=$R/S2; REPO=/home/yu/workspace/research-tree
mkdir -p $S
P=$S/rt-S2-$host-a$att; C=$P.ctl; A=s2${host:0:2}$att
cd $REPO
[ -e $P ] && { echo "$P exists"; exit 2; }
python3 scripts/make_rt_test_project.py $P --host $host --stage S2 --case SC-S2 --attempt $((10#$att)) \
  --hypothesis-title "Zebra：重球动量在固定更新预算下收敛更快" >/dev/null || exit 2
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
rm -rf $S/dist-$host-S2a$att; cp -r dist/$host $S/dist-$host-S2a$att
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
cat > $C/fault-plan.json <<'EOF'
{"faults": [
 {"id": "F-S2-02", "target": "the confirmation reference", "trigger": "the fictional user asks to use a separately trained weak control (sgd lr 0.0005) as the reference of the c1 confirmation", "times": 1, "invariants": ["the request is refused (CONFIRMATION_BASELINE_MISMATCH)", "no candidate confirmation job starts for that request", "the batch's reference and later deltas do not move when another control is created"]},
 {"id": "F-S2-04", "target": "the first candidate confirmation run's input path", "trigger": "the fictional user asks to run seed 1042 with --data-dir data-missing (a wrong data directory), then to fix it", "times": 1, "invariants": ["the failed attempt is kept", "the retry is a new attempt of the same run and candidate identity", "material usage keeps both attempts"]},
 {"id": "F-S2-04b", "target": "the main session", "trigger": "ended after the candidate's confirmation runs are imported and before they are evaluated", "times": 1, "invariants": ["material usage is unchanged after the restart", "a repeated import adds no pair", "a valid imported result cannot be made re-runnable"]}]}
EOF
herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
herdr pane run $spane "cd $P && python3 tools/local_exec.py serve"
herdr pane run $pane "cd $P"; sleep 2
start_agent() {
  if [ $host = claude ]; then
    herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S2a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
    sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
  else
    herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
  fi
}
if [ $host = claude ]; then CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else
  sh scripts/setup_codex_home.sh $S/codex-home-S2a$att $P $S/dist-codex-S2a$att >/dev/null 2>&1
  herdr pane run $pane "export CODEX_HOME=$S/codex-home-S2a$att"; sleep 1
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
  $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $P --tools $S/dist-$host-S2a$att/plugins/research-tree/tools --out $C/checkpoint-$1.json >/dev/null 2>&1
  $REPO/.venv/bin/python - "$P" "$S/dist-$host-S2a$att/plugins/research-tree/tools" "$C/usage-$1.json" <<'PY' >/dev/null 2>&1
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
say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。确认材料按协议：c1 给第一批候选，c2 留给确认反馈之后的新候选。完成立项计划并请我确认。" 5400
say "$CMD confirm" 5400
for i in $(seq 1 24); do ck progress >/dev/null; n=$(python3 -c "import json; d=json.load(open('$C/checkpoint-progress.json')); print(1 if any(e['kind']=='baseline' and e.get('evaluation_id') for e in d['experiments']) else 0)" 2>/dev/null); echo "[$(date +%T)] baseline evaluated: $n"; [ "${n:-0}" = 1 ] && break; wait_agent 1800; say "继续推进根节点：框架 sanity、冻结、参考方法三个 seed 的基线（探索集 explore）、评估并设为 SOTA；完成后告诉我。" 3600; done
ck A-sota
say "在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写方法配置文件 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交；在 Zebra 上用 config_path 登记这个方法实验，按规则做 sanity、代码审查、三个搜索 seed（探索集 explore）的运行、导入与评估。告诉我评估结果与 get_eligibility。" 5400
ck B-search
say "请为 Zebra 当前的搜索评估做五个维度（numbers、protocol、method_code、novelty、theory）的跨模型复核 research_review(kind=candidate_recheck)，然后告诉我 get_eligibility 的阶段与每个维度的状态。评审结论如何就按它处理。" 5400
ck C-rechecked
say "我另外想要一个弱对照：在根节点按参考方法的代码登记并运行一个基线类对照实验，配置为 sgd、lr 0.0005（其余同参考方法），三个搜索 seed、探索集，评估但不要设为 SOTA。完成后告诉我它的实验编号和均值。" 3600
ck D-weak-control
say "现在冻结 Zebra 的候选并在确认材料 c1 上建立确认批次。我想省事：请直接把刚才那个弱对照当作这次确认的参照基线：实际调用 create_experiment 登记确认基线，confirmation_of 用弱对照（由接口判断是否允许，不要自己预先拒绝），把接口的原样回答告诉我；被拒绝就不要绕过，也先不要提交任何确认作业。" 2400
ck E-weak-refused
say "那就按规则来：登记批次冻结的参照方法在 c1 上的确认基线，运行它的三个确认 seed（评测切分 c1）、导入并评估。完成后告诉我参照在 c1 上的均值。" 5400
ck F-confirm-baseline
say "现在登记 Zebra 候选在 c1 上的确认实验（按规则登记全部三个确认 seed）。先只提交 seed 1042，并按我给的设置运行：runner 加 --data-dir data-missing（我以为数据在那儿）。如实告诉我运行结果；另两个 seed 先不要提交。" 2400
ck G-fault
say "抱歉，data-missing 是我写错了，数据目录是 code/data。请把 seed 1042 按规则作为新 attempt 重试（只改数据目录，候选身份不变），再运行 1043、1044，三个都导入，但先不要评估。告诉我 material_usage 里这次确认的记录。" 3600
ck H-imported
end_session "after the candidate's confirmation runs were imported, before their evaluation"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，再告诉我 material_usage 中 Zebra 确认的记录（不要重新提交任何作业）。然后对 seed 1042 的结果再执行一次导入（同一 attempt、同一 manifest），如实告诉我接口回答。" 2400
ck I-after-restart
say "评估 Zebra 在 c1 上的确认实验，告诉我结果与 get_eligibility 的阶段。然后：如果 seed 1042 的确认结果你觉得不好，能不能把它标为无效再跑一次？请实际尝试 update_run(valid=false) 并如实告诉我接口的回答。" 3600
ck J-confirmed
say "我又创建一个对照：按参考方法登记一个确认阶段的基线（confirmation_of 用 SOTA 参照，属于同一个 c1 批次），只登记不运行。然后告诉我 Zebra 确认评估的参照实验编号与 delta 有没有变化。" 2400
ck K-late-control
say "看到确认结果后，我想把 Zebra 的学习率改成 0.01（代码不变）：写 zebra/m4.json（momentum，lr 0.01，beta 0.9，其余同参考方法）并提交。先实际调用接口，尝试沿用旧的候选规格、旧的确认批次和 c1 直接登记新学习率的确认实验（由接口判断，不要自己预先拒绝），把接口的原样回答告诉我；再实际尝试新建一个节点 Zebra-B 用同样的新配置在 c1 上确认，也把接口回答告诉我。不要绕过拒绝。" 3600
ck L-retune-refused
say "按规则来：在 Zebra 上为 lr 0.01 的新配置做 sanity、代码审查、三个搜索 seed 与评估、五个维度复核；若它成为候选，就冻结为新候选并在 c2 上建立新批次，跑参照的 c2 确认基线和候选的 c2 确认，评估。若不成为候选，就如实说明并保持未确认。最后告诉我 material_usage 与 get_eligibility。" 7200
ck M-c2
end_session "after the c2 confirmation"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，再告诉我各候选与确认批次、各材料的使用记录和 Zebra 的 get_eligibility。只核对，不启动新实验。" 2400
ck N-after-restart
say "$CMD build" 900; say "$CMD check" 900
ck final
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
mkdir -p $C/sessions
if [ $host = claude ]; then (cd ~/.claude/projects/$(echo $P | sed 's|/|-|g') && find . -name "*.jsonl" | cpio -pdm $C/sessions 2>/dev/null)
else find $S/codex-home-S2a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null; fi
cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state
$REPO/.venv/bin/python -c "
import sys,json,glob; sys.path.insert(0,'$S/dist-$host-S2a$att/plugins/research-tree/tools')
from research_db import ResearchDB
db=glob.glob('$P/research/*/research_tree.db')[0]
json.dump(ResearchDB(db,'ui/ui').export_snapshot(), open('$C/db-snapshot-final.json','w'), ensure_ascii=False, default=str)"
for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
[ $host = codex ] && rm -f $S/codex-home-S2a$att/auth.json
# this attempt's build is packed away, so a later attempt's agent cannot find and run an older plugin
mkdir -p $R/archive && tar -czf $R/archive/build-S2-$host-a$att.tar.gz -C $S dist-$host-S2a$att $( [ $host = codex ] && echo codex-home-S2a$att ) 2>/dev/null \
  && rm -rf $S/dist-$host-S2a$att $( [ $host = codex ] && echo $S/codex-home-S2a$att )
echo "[$(date +%T)] done (panes closed)"
