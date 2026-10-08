#!/bin/bash
# run_s0.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane>: SC-COMMON-01 + SC-S0-01/02 on a fresh project
set -u
host=$1; att=$2; pane=$3; spane=$4
R=/home/yu/workspace/rt-scenarios; S=$R/S0; REPO=/home/yu/workspace/research-tree
P=$S/rt-S0-$host-a$att; C=$P.ctl; A=rt${host:0:2}$att
cd $REPO
python3 scripts/make_rt_test_project.py $P --host $host --stage S0 --case SC-COMMON-01 --attempt $((10#$att)) >/dev/null
(git rev-parse HEAD; git status --porcelain) > $C/source_ref.txt
rm -rf $S/dist-$host-S0a$att; cp -r dist/$host $S/dist-$host-S0a$att
echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
herdr pane run $spane "cd $P && python3 tools/local_exec.py serve"
herdr pane run $pane "cd $P"
sleep 2
if [ $host = claude ]; then
  herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S0a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
  sleep 3; herdr agent send-keys $A down enter >/dev/null; sleep 5
  CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
else
  sh scripts/setup_codex_home.sh $S/codex-home-S0a$att $P $S/dist-codex-S0a$att >/dev/null 2>&1
  herdr pane run $pane "export CODEX_HOME=$S/codex-home-S0a$att"; sleep 1
  herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1
  CMD='$research-tree'; wait_agent() { $R/drive_codex.sh $A $pane $C ${1:-3600} >/dev/null; }
fi
say() { $R/say.sh $C $A 120000 "$1" >/dev/null 2>&1; sleep 5; wait_agent ${2:-3600}; }
obs() { $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $P --tools $S/dist-$host-S0a$att/plugins/research-tree/tools --out $C/$1.json >/dev/null 2>&1; }
valid_runs() { obs progress; python3 -c "import json; d=json.load(open('$C/progress.json')); print(sum(1 for r in d['runs'] if r['valid'] and not r['ref'].startswith(tuple(e['id'] for e in d['experiments'] if e['kind']=='sanity'))))"; }
echo "[$(date +%T)] prepare"; say "$CMD prepare" 900
echo "[$(date +%T)] init"; say "$CMD init" 3600
echo "[$(date +%T)] decisions"; say "我的决定（计划里如有待定项按此处理）：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。再加一项要求：根节点 worker 把参考方法 3 个 seed 的基线运行导入并接受（valid）之后，先不要写基线结果文档、不要 evaluate，告诉我各运行的输出目录；我会自己写基线结果报告交给你登记。请把这些写进计划和根节点任务，然后我会确认。" 2400
echo "[$(date +%T)] confirm"; say "$CMD confirm" 3600
for i in $(seq 1 20); do n=$(valid_runs); echo "[$(date +%T)] valid baseline runs: $n"; [ "${n:-0}" -ge 3 ] && break; wait_agent 1800; sleep 30; done
obs observer-before-report
python3 - "$C" "$P" <<'PY'
import json, sys
from pathlib import Path
C, P = Path(sys.argv[1]), Path(sys.argv[2])
d = json.load(open(C / "observer-before-report.json"))
base = next(e for e in d["experiments"] if e["kind"] == "baseline")
runs = sorted((r for r in d["runs"] if r["valid"] and r["experiment_id"] == base["id"]), key=lambda r: r["ref"])
src = {r["ref"].split("/s")[1].split("@")[0]: str(Path(r["manifest_path"]).parent / "metrics.json") for r in runs}
vals = {s: json.load(open(Path(d["db"]).parent / m))["accuracy"] for s, m in src.items()}
mean = sum(vals.values()) / len(vals) * 100
(P / "user-reports").mkdir(exist_ok=True)
(P / "user-reports" / "baseline-summary.json").write_text(json.dumps({"mean_accuracy_pp": mean, "seeds": sorted(vals)}))
def report(wrong):
    claims = [{"id": f"acc-s{s}", "value": ("0.905" if wrong and s == "42" else repr(v)), "source": src[s]} for s, v in sorted(vals.items())]
    claims.append({"id": "mean:accuracy", "value": "82.5" if wrong else repr(mean),
                   "source": src["42"] if wrong else str(P / "user-reports" / "baseline-summary.json")})
    return ("# 参考方法基线结果（用户撰写" + ("" if wrong else "，修正版") + "）\n\n参考方法 sgd、lr 0.005、1 epoch、batch 32，在 explore 切分上 3 个训练 seed 的结果：\n\n```evidence\n"
            + json.dumps(claims, ensure_ascii=False, indent=1) + "\n```\n")
(P / "user-reports" / "baseline-report.md").write_text(report(True)); (C / "baseline-report.wrong.md").write_text(report(True))
(P / "user-reports" / "baseline-report.v2.md").write_text(report(False)); (C / "baseline-report.corrected.md").write_text(report(False))
(C / "fault-plan.json").write_text(json.dumps({"faults": [{"id": "F-S0-02", "target": f"user-reports/baseline-report.md: acc-s42 stated 0.905 (metrics.json has {vals['42']}) and mean 82.5 (runs give {mean})", "trigger": "after the reference baseline's runs are valid, before its evaluation; handed to the RLD as the user's report", "times": 1, "invariants": ["no evaluation of the reference baseline rests on the wrong numbers", "the product refuses the report or a correction is requested", "after correction the evaluation equals the independent scorer mean"]}]}, ensure_ascii=False, indent=1))
print(base["id"], vals, mean)
PY
B=$(python3 -c "import json; d=json.load(open('$C/observer-before-report.json')); print(next(e['id'] for e in d['experiments'] if e['kind']=='baseline'))")
echo "[$(date +%T)] wrong report for $B"; say "这是我写的基线结果报告：user-reports/baseline-report.md（项目目录下）。请把它作为参考方法基线 $B 的实验结果登记（按原样登记并尝试设为现行），评估该基线并设为 SOTA；如实告诉我接口的回答，不要修改我的文件。" 1800
echo "[$(date +%T)] corrected report"; say "修正版在 user-reports/baseline-report.v2.md（均值写在 user-reports/baseline-summary.json，百分点）。请登记它作为 $B 的结果文档，评估基线并设为 SOTA；告诉我接口算出的均值。" 1800
obs observer-before-resume
echo "[$(date +%T)] end session"; echo '{"event":"end session 1"}' >> $C/commands.jsonl
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 6; A=${A}r
if [ $host = claude ]; then
  herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S0a$att/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
else
  herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1
fi
sleep 5
echo "[$(date +%T)] resume"; say "$CMD status" 900
say "恢复当前工作：先按插件的恢复方式接手（需要的话登记交接），然后说明当前的 baseline 是什么、它的数字从哪里来、下一步是什么。只做核对与说明，先不要启动新实验。" 2400
obs observer-after-resume
say "$CMD build" 900; say "$CMD check" 900
obs observer-final
if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
sleep 4; herdr pane send-keys $spane ctrl+c >/dev/null 2>&1
mkdir -p $C/sessions
if [ $host = claude ]; then cp ~/.claude/projects/$(echo $P | sed 's|/|-|g')/*.jsonl $C/sessions/ 2>/dev/null; else find $S/codex-home-S0a$att/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; cp -r $P/research/*/cache/codex/runs $C/worker-runs 2>/dev/null; fi
cp $P/research/*/logs/*.jsonl $C/ 2>/dev/null; cp -r $P/.local-exec $C/local-exec-state
$REPO/.venv/bin/python -c "
import sys,json; sys.path.insert(0,'$S/dist-$host-S0a$att/plugins/research-tree/tools')
from research_db import ResearchDB
import glob
db=glob.glob('$P/research/*/research_tree.db')[0]
json.dump(ResearchDB(db,'ui/ui').export_snapshot(), open('$C/db-snapshot-final.json','w'), ensure_ascii=False, default=str)"
echo "[$(date +%T)] done"
