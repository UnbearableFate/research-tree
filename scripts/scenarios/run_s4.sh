#!/bin/bash
# run_s4.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane>
# S4 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §8.7):
# SC-COMMON-01 prefix; SC-S4-01 (a real reviewer checks a summary whose numbers contradict the metrics; the finding is
# recorded once, survives a restart, and closes only by an explicit resolution with a new passing review); SC-S4-02
# (novelty without the foundational paper: one literature follow-up in the same session, nothing re-run after a
# restart); SC-S4-03 (a same-family reviewer refused before any call; the backend unavailable for one session — no
# fallback, no self-review; then a real cross-family review); SC-S4-04 (an altered code snapshot gives no method_code
# pass; the real one does); SC-COMMON-01 suffix. Checkpoints after every step; panes closed, build packed at the end.
set -u
confirm_exit() {  # Claude Code asks before stopping running background tasks: confirm, or the old session stays
  sleep 4
  if herdr pane read $pane 2>/dev/null | tail -15 | grep -q "Exit and stop tasks"; then
    herdr pane send-keys $pane Enter >/dev/null 2>&1
    echo '{"event":"confirmed the Claude Code exit dialog (background tasks were running)"}' >> $C/commands.jsonl; sleep 3
  fi
}
host=$1; att=$2; pane=$3; spane=$4
R=/home/yu/workspace/rt-scenarios; S=$R/S4; REPO=/home/yu/workspace/research-tree
mkdir -p $S
P=$S/rt-S4-$host-a$att; C=$P.ctl; A=s4${host:0:2}$att
cd $REPO
[ -e $P ] && { echo "$P exists"; exit 2; }
python3 scripts/make_rt_test_project.py $P --host $host --stage S4 --case SC-S4 --attempt $((10#$att)) \
  --hypothesis-title "Zebra：重球动量在固定更新预算下收敛更快" >/dev/null || exit 2
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
rm -rf $S/dist-$host-S4a$att; cp -r dist/$host $S/dist-$host-S4a$att
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
cp $REPO/scripts/scenarios/s4_fault_plan.json $C/fault-plan.json
herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
herdr pane run $spane "cd $P && python3 tools/local_exec.py serve"
herdr pane run $pane "cd $P"; sleep 2
start_agent() {
  if [ $host = claude ]; then
    herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S4a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
    sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
  else
    herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
  fi
}
if [ $host = claude ]; then CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else
  sh scripts/setup_codex_home.sh $S/codex-home-S4a$att $P $S/dist-codex-S4a$att >/dev/null 2>&1
  herdr pane run $pane "export CODEX_HOME=$S/codex-home-S4a$att"; sleep 1
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
  $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $P --tools $S/dist-$host-S4a$att/plugins/research-tree/tools --out $C/checkpoint-$1.json >/dev/null 2>&1
  $REPO/.venv/bin/python - "$P" "$S/dist-$host-S4a$att/plugins/research-tree/tools" "$C/usage-$1.json" <<'PY' >/dev/null 2>&1
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
say "在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写方法配置文件 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交；在 Zebra 上用 config_path 登记这个方法实验，按规则做 sanity、代码审查、三个搜索 seed 的运行、导入与评估，并写好结果文档。告诉我评估结果与 get_eligibility。" 5400
ck B-zebra
$REPO/.venv/bin/python $REPO/scripts/scenarios/s4_wrong_report.py $C $P $S/dist-$host-S4a$att/plugins/research-tree/tools >/dev/null
python3 -c 'import json,sys; print(json.dumps({"event": "controller wrote a report copy that contradicts the metrics (F-S4-01)", "record": json.load(open(sys.argv[1]))}))' $C/fault-applied.json >> $C/commands.jsonl
say "我在研究目录 docs/reports/zebra-summary-draft.md 写了一份 Zebra 的结果摘要（数字是我手抄的）。请把它作为 numbers 维度要复核的结果文档，为 Zebra 当前评估做一次真实的跨模型复核 research_review(kind=candidate_recheck, dimension=numbers)，brief 只列文件与元数据。如实告诉我回执的结论、各清单项和是否产生了未决问题。" 3600
ck C-numbers-reviewed
end_session "after the numbers review"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手。告诉我未决问题（obligations）列表；然后把刚才那份 numbers 回执再登记一次是否会增加问题——不要重新调用 reviewer，只查看接口与记录。" 2400
ck D-after-restart
say "那份摘要是我抄错了。请写一份数字取自指标文件与统计文件的正确结果文档（新版本），再为 numbers 维度做一次新的真实复核；若这次通过，就用这份新回执按规则 resolve 对应的未决问题，然后告诉我 get_eligibility 和其余仍未关闭的问题。" 3600
ck E-resolved
say "请为 Zebra 做 novelty 维度的真实复核。我注意到假说的相关文献里没有动量法的基础论文（Polyak 1964, Some methods of speeding up the convergence of iteration methods），brief 里不要替 reviewer 补上。若 reviewer 返回 uncertain 并列出 requested_queries，就用 literature_followup 执行一次补查，再在原会话里带上补查结果重新复核；若 reviewer 已能判定，就如实记录，不要强迫它要求补查。告诉我每一轮的结论与补查记录。" 5400
ck F-novelty
end_session "after the novelty follow-up"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，告诉我 novelty 复核与补查的当前状态（已完成的查询不要重跑）。" 2400
ck G-after-restart
python3 $REPO/scripts/scenarios/s4_edit_reviewer.py $P/research-tree.yaml same-family $host
echo '{"event":"fictional user edited research-tree.yaml: models.reviewer to the Leader'"'"'s own family (F-S4-03a)"}' >> $C/commands.jsonl
say "我把 research-tree.yaml 的 reviewer 改成了和你同一家族的模型。请让配置生效（$CMD config apply），然后为 Zebra 做一次 theory 维度的复核，如实告诉我结果；不要用自评代替。" 2400
ck H-same-family
python3 $REPO/scripts/scenarios/s4_edit_reviewer.py $P/research-tree.yaml restore $host
echo '{"event":"fictional user restored models.reviewer in research-tree.yaml"}' >> $C/commands.jsonl
say "我把 reviewer 改回原来的设置了，请让配置生效，暂时不要评审。" 1200
# the next session starts with the reviewer backend unavailable on its PATH (F-S4-03b)
echo '{"event":"end session (before the unavailable-backend check)"}' >> $C/commands.jsonl
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; shimmed=pi; else herdr agent prompt $A "/quit" >/dev/null 2>&1; shimmed=claude; fi
sleep 6
mkdir -p $C/shim-$shimmed
printf '#!/bin/sh\necho "%s: not logged in (S4 controller shim)" >&2\nexit 1\n' "$shimmed" > $C/shim-$shimmed/$shimmed; chmod +x $C/shim-$shimmed/$shimmed
herdr pane run $pane "export PATH=$C/shim-$shimmed:\$PATH"; sleep 1
echo "{\"event\":\"controller started the next session with the reviewer backend ($shimmed) answering not-logged-in on its PATH (F-S4-03b)\"}" >> $C/commands.jsonl
A=${A}u; start_agent
say "$CMD status" 900
say "请为 Zebra 做一次 theory 维度的跨模型复核，如实告诉我结果；后端不可用时不要换后端，也不要自评。" 2400
ck I-unavailable
echo '{"event":"end session (after the unavailable-backend check)"}' >> $C/commands.jsonl
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 6
herdr pane run $pane "export PATH=\$(echo \$PATH | sed 's#$C/shim-$shimmed:##')"; sleep 1
echo '{"event":"controller restored the PATH for the next session"}' >> $C/commands.jsonl
A=${A}v; start_agent
say "$CMD status" 900
say "后端恢复了。请为 Zebra 做 theory 维度的真实跨模型复核，告诉我回执的观测模型、后端与结论；已完成的复核不要重做。" 3600
ck J-theory
$REPO/.venv/bin/python $REPO/scripts/scenarios/s4_hide_snapshot.py hide $C $P $S/dist-$host-S4a$att/plugins/research-tree/tools >/dev/null
python3 -c 'import json,sys; print(json.dumps({"event": "controller moved the review code snapshot away and pointed the brief directory at another version (F-S4-04)", "record": json.load(open(sys.argv[1]))}))' $C/snapshot-fault.json >> $C/commands.jsonl
say "请为 Zebra 做 method_code 维度的真实复核（读取所审提交的代码），如实告诉我回执结论、证据核验结果与资格状态。" 3600
ck K-method-code-missing
$REPO/.venv/bin/python $REPO/scripts/scenarios/s4_hide_snapshot.py restore $C $P >/dev/null
echo '{"event":"controller restored the code snapshot (F-S4-04)"}' >> $C/commands.jsonl
say "代码快照恢复了。请再做一次 method_code 维度的真实复核，告诉我结论、证据核验与资格状态。" 3600
ck L-method-code
end_session "at the end"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手，再告诉我各复核维度的状态、未决问题与 get_eligibility。只核对，不重做评审。" 2400
ck M-after-restart
say "$CMD build" 900; say "$CMD check" 900
ck final
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
mkdir -p $C/sessions
if [ $host = claude ]; then cp ~/.claude/projects/$(echo $P | sed 's|/|-|g')/*.jsonl $C/sessions/ 2>/dev/null
else find $S/codex-home-S4a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null; fi
cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state
$REPO/.venv/bin/python -c "
import sys,json,glob; sys.path.insert(0,'$S/dist-$host-S4a$att/plugins/research-tree/tools')
from research_db import ResearchDB
db=glob.glob('$P/research/*/research_tree.db')[0]
json.dump(ResearchDB(db,'ui/ui').export_snapshot(), open('$C/db-snapshot-final.json','w'), ensure_ascii=False, default=str)"
for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
[ $host = codex ] && rm -f $S/codex-home-S4a$att/auth.json
# this attempt's build is packed away, so a later attempt's agent cannot find and run an older plugin
mkdir -p $R/archive && tar -czf $R/archive/build-S4-$host-a$att.tar.gz -C $S dist-$host-S4a$att $( [ $host = codex ] && echo codex-home-S4a$att ) 2>/dev/null \
  && rm -rf $S/dist-$host-S4a$att $( [ $host = codex ] && echo $S/codex-home-S4a$att )
echo "[$(date +%T)] done (panes closed)"
