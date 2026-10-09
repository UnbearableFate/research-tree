#!/bin/bash
# run_s1.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane>
# S1 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §5.4):
# SC-COMMON-01 prefix, SC-S1-01 (discovery candidates Zebra/Alpha: Alpha reviewed, then changed, then a restart while
# its receipts are for the old revision), SC-S1-03 (method identity from committed configuration files), SC-S1-02
# (claim broadening and narrowing), a session restart, SC-COMMON-01 suffix. Both panes are closed at the end. The controller only types what the fictional
# user says through the host's normal entry; after every step it keeps a read-only snapshot (checkpoint-*.json)
# and a copy of the discovery candidate pool. Declared faults: fault-plan.json.
set -u
host=$1; att=$2; pane=$3; spane=$4
R=/home/yu/workspace/rt-scenarios; S=$R/S1; REPO=/home/yu/workspace/research-tree
mkdir -p $S
P=$S/rt-S1-$host-a$att; C=$P.ctl; A=s1${host:0:2}$att
cd $REPO
[ -e $P ] && { echo "$P exists"; exit 2; }
python3 scripts/make_rt_test_project.py $P --host $host --stage S1 --case SC-S1 --attempt $((10#$att)) \
  --discovery precheck --hypothesis-title "Zebra：重球动量在固定更新预算下收敛更快" >/dev/null || exit 2
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
rm -rf $S/dist-$host-S1a$att; cp -r dist/$host $S/dist-$host-S1a$att
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
cat > $C/fault-plan.json <<'EOF'
{"faults": [{"id": "F-S1-03", "target": "the Zebra node's method configuration file in its worktree (configs/momentum*.json)", "trigger": "after the experiments are registered, before the first run is imported: the controller changes lr in the file the runner reads", "times": 1, "invariants": ["the run reporting another configuration is not imported under the old identity", "no evaluation rests on it", "after the file is restored the run imports"]}]}
EOF
herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
herdr pane run $spane "cd $P && python3 tools/local_exec.py serve"
herdr pane run $pane "cd $P"; sleep 2
start_agent() {
  if [ $host = claude ]; then
    herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S1a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
    sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
  else
    herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
  fi
}
if [ $host = claude ]; then CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else
  sh scripts/setup_codex_home.sh $S/codex-home-S1a$att $P $S/dist-codex-S1a$att >/dev/null 2>&1
  herdr pane run $pane "export CODEX_HOME=$S/codex-home-S1a$att"; sleep 1
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
ck() {  # read-only checkpoint: observer, discovery pool, eligibility of every node
  $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $P --tools $S/dist-$host-S1a$att/plugins/research-tree/tools --out $C/checkpoint-$1.json >/dev/null 2>&1
  root=$(ls -d $P/research/*/ 2>/dev/null | head -1)
  [ -n "$root" ] && cp ${root}docs/project/discovery/candidates.json $C/candidates-$1.json 2>/dev/null
  [ -n "$root" ] && cp ${root}cache/discovery/state.json $C/discovery-state-$1.json 2>/dev/null
  echo "[$(date +%T)] checkpoint $1"
}
end_session() {
  echo "{\"event\":\"end session ($1)\"}" >> $C/commands.jsonl
  if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
  sleep 6; A=${A}r; start_agent
}
echo "[$(date +%T)] prepare"; say "$CMD prepare" 900
echo "[$(date +%T)] init"; say "$CMD init" 5400
say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。立项前的发现流程（precheck：文献、查新、批判性评审、发现门）请完整走完，然后告诉我发现门的结论和每个候选的编号。" 5400
ck A-discovery
say "我想再加一个用户假说：Alpha：学习率预热（前 10% 更新步线性升温）可能让 SGD 在一轮内更稳。请按发现流程把它加入用户假说文件并重新 merge 候选，不要删改 Zebra；然后为 Alpha 做真实的查新与批判性评审（research_review），再运行发现门，告诉我门的结论和每个候选的编号与 revision。评审结论如何就按它处理。" 3600
ck B-alpha-reviewed
say "Alpha 的机制改一下：不用预热，改为余弦学习率衰减（标题不变，只改用户假说文件里它的说明与机制），重新 merge，再运行发现门，告诉我 Alpha 的编号和 revision、门的结论。这一步先不要为 Alpha 重新评审。" 2400
ck C-alpha-changed
end_session "after Alpha changed, before its new reviews"
say "$CMD status" 900
say "恢复当前工作：不要改动任何候选或评审，重新 merge 一次候选，再运行一次发现门，告诉我结论和每个候选的编号与 revision。" 2400
ck D-gate-after-restart
say "现在请为 Alpha 的当前版本做真实的查新与批判性评审（research_review），然后重新运行发现门，告诉我结论；评审结论如何就按它处理，不要预设 Alpha 应该通过。" 3600
ck E-alpha-rereviewed
say "立项计划只建 Zebra 一个初始节点即可（Alpha 留待以后）。请据此完成或更新立项计划并请我确认。" 3600
say "$CMD confirm" 5400
for i in $(seq 1 24); do ck progress >/dev/null; n=$(python3 -c "import json; d=json.load(open('$C/checkpoint-progress.json')); print(1 if any(e['kind']=='baseline' and e.get('evaluation_id') for e in d['experiments']) else 0)" 2>/dev/null); echo "[$(date +%T)] baseline evaluated: $n"; [ "${n:-0}" = 1 ] && break; wait_agent 1800; say "继续推进根节点：框架 sanity、冻结、参考方法三个 seed 的基线、评估并设为 SOTA；完成后告诉我。" 3600; done
ck F-sota
say "请在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写三个方法配置文件并提交到同一个提交：zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）、zebra/m2.json（与 m1 完全相同，只多一个 output_dir 字段指向另一个输出目录）、zebra/m3.json（momentum，lr 0.01，beta 0.9，其余同参考方法）。然后在 Zebra 上用这个提交和 config_path 登记三个方法实验（运行时 runner 用 --config 读对应文件），先不要运行。告诉我三个实验的方法身份（method_spec）是否相同，以及为什么。" 3600
ck G-identities
$REPO/.venv/bin/python - "$C" "$P" "$S/dist-$host-S1a$att/plugins/research-tree/tools" <<'PY'
import glob, json, sys
from pathlib import Path
C, P, tools = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, tools)
from research_db import ResearchDB
db = ResearchDB(glob.glob(f"{P}/research/*/research_tree.db")[0], "ui/ui")
places = [Path(b["worktree_path"]) for b in db.find("branch") if b.get("worktree_path")]
places += [P / "code"]
record = {"changed": [], "searched": [str(x) for x in places]}
for place in places:
    for path in sorted(place.rglob("*.json")) if place.is_dir() else []:
        if ".git" in path.parts or "outputs" in path.parts or "data" in path.parts:
            continue
        try:
            cfg = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(cfg, dict) and cfg.get("method") == "momentum" and cfg.get("lr") == 0.005 and "zebra" in path.parts:
            (C / f"fault-original-{len(record['changed'])}.json").write_text(path.read_text())
            path.write_text(json.dumps({**cfg, "lr": 0.02}, indent=1) + "\n")
            record["changed"].append(str(path))
(C / "fault-applied.json").write_text(json.dumps(record, indent=1))
print(record)
PY
python3 -c 'import json,sys; print(json.dumps({"event": "controller fault F-S1-03 applied", "record": json.load(open(sys.argv[1]))}))' $C/fault-applied.json >> $C/commands.jsonl
say "请运行实验①的 seed 42（按项目流程提交、等待、导入），如实告诉我导入结果；如果接口拒绝，告诉我拒绝的原因，不要改配置文件来绕过。" 3600
ck H-config-drift
python3 - "$C" <<'PY'
import json, sys
from pathlib import Path
C = Path(sys.argv[1])
rec = json.loads((C / "fault-applied.json").read_text())
for i, path in enumerate(rec["changed"]):
    Path(path).write_text((C / f"fault-original-{i}.json").read_text())
rec["restored"] = rec["changed"]
(C / "fault-applied.json").write_text(json.dumps(rec, indent=1))
PY
echo '{"event":"controller restored the configuration file(s) of F-S1-03"}' >> $C/commands.jsonl
say "我已把被改动的配置文件恢复原样。请把实验①按规则走完：sanity（投影到实验①的方法身份）、代码审查、三个 seed 运行、导入、评估；然后尝试提交实验③的 seed 42，如实告诉我接口的回答（不要为③另做 sanity 或审查）。" 5400
ck I-zebra-evaluated
say "请为 Zebra 当前的评估做 GO 候选所需的跨模型复核：numbers、protocol、method_code、novelty、theory 五个维度各一次 research_review(kind=candidate_recheck)，然后告诉我 get_eligibility 中每个维度的状态。若评估未过门槛，就如实告诉我，并仍为当前评估做这五个维度的复核。" 5400
ck J-rechecked
say "这是我的决定（我想看看复核会如何反应，之后会收回）：把 Zebra 的主张扩大为“重球动量在所有数据分布上都有收敛保证”。请照此写新版本的假说文档（主张、Claim map 与适用范围都改）并登记为 Zebra 的新主张版本；你认为证据不足就在文档里写明，但仍然登记。然后告诉我主张版本号、哪些复核还有效、哪些失效，以及数字有没有变。" 2400
ck K-claim-broadened
say "那个扩大的主张没有证据，请恢复为原来的范围（只限本合成任务、固定更新预算）作为新的主张版本，并只为受影响的维度重新做复核；告诉我结果。" 5400
ck L-claim-narrowed
end_session "after the claim revisions"
say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手（需要的话登记交接），再告诉我 Zebra 的主张版本、各复核维度的状态和发现门的结论。只核对，不启动新实验。" 2400
ck M-after-restart
say "$CMD build" 900; say "$CMD check" 900
ck final
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 4; herdr pane send-keys $(cat $C/scheduler-pane.txt) ctrl+c >/dev/null 2>&1
mkdir -p $C/sessions
if [ $host = claude ]; then cp ~/.claude/projects/$(echo $P | sed 's|/|-|g')/*.jsonl $C/sessions/ 2>/dev/null
else find $S/codex-home-S1a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null; fi
cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state
$REPO/.venv/bin/python -c "
import sys,json,glob; sys.path.insert(0,'$S/dist-$host-S1a$att/plugins/research-tree/tools')
from research_db import ResearchDB
db=glob.glob('$P/research/*/research_tree.db')[0]
json.dump(ResearchDB(db,'ui/ui').export_snapshot(), open('$C/db-snapshot-final.json','w'), ensure_ascii=False, default=str)"
for p in $(cat $C/pane.txt) $(cat $C/scheduler-pane.txt); do herdr pane close $p >/dev/null 2>&1; done
[ $host = codex ] && rm -f $S/codex-home-S1a$att/auth.json
# this attempt's build is packed away, so a later attempt's agent cannot find and run an older plugin
mkdir -p $R/archive && tar -czf $R/archive/build-S1-$host-a$att.tar.gz -C $S dist-$host-S1a$att $( [ $host = codex ] && echo codex-home-S1a$att ) 2>/dev/null \
  && rm -rf $S/dist-$host-S1a$att $( [ $host = codex ] && echo $S/codex-home-S1a$att )
echo "[$(date +%T)] done (panes closed)"
