#!/bin/bash
# run_s3_upgrade.sh <host claude|codex> <attempt> <agent-pane> <scheduler-pane> <old-project> <new-dist-root>
# SC-S3-03 (plans/research-tree-implementation-and-real-scenarios.md §7.5): a real project an earlier build made on this
# host (e.g. an S1 scenario project: real runs, imports without recorded units) is upgraded by the new build, twice:
# on a copy whose original run manifests are all there ("kept") and on a copy whose manifests were moved away ("moved").
# Each copy is shown to the agent at the old project's absolute path through a bwrap bind (the database, the marker
# and the worktrees name that path), so nothing in the old records is edited by hand and the original stays as it
# was. The fictional user asks for the plugin's own upgrade and migration path; the controller keeps read-only
# checkpoints before and after, and after a restart. Panes are closed at the end.
set -u
host=$1; att=$2; pane=$3; spane=$4; OLD=$(readlink -f "$5"); NEW=$(readlink -f "$6")
R=/home/yu/workspace/rt-scenarios; S=$R/S3; REPO=/home/yu/workspace/research-tree
mkdir -p $S
[ -d "$OLD/research" ] || { echo "$OLD is not a project"; exit 2; }
cd $REPO
for variant in kept moved; do
  P=$S/upgrade-$host-a$att-$variant; C=$P.ctl; A=s3u${host:0:2}$att${variant:0:1}
  [ -e $P ] && { echo "$P exists"; exit 2; }
  mkdir -p $C
  cp -a "$OLD" "$P"
  (git rev-parse HEAD; git -C $(dirname $NEW) rev-parse HEAD 2>/dev/null; git status --porcelain) > $C/source_ref.txt
  sha256sum $(ls $OLD/research/*/research_tree.db) > $C/old-db.sha256
  rm -rf $S/dist-$host-S3u$att$variant; cp -r $NEW/$host $S/dist-$host-S3u$att$variant
  echo "{\"old_project\": \"$OLD\", \"copy\": \"$P\", \"variant\": \"$variant\"}" > $C/scenario.json
  if [ $variant = moved ]; then
    mkdir -p $C/moved-manifests
    (cd $P && find . -name run_manifest.json -not -path "*/.git/*" | while read f; do
       mkdir -p "$C/moved-manifests/$(dirname "$f")"; mv "$f" "$C/moved-manifests/$f"; echo "$f"; done) > $C/moved-manifests.txt
    echo "{\"event\":\"controller moved $(wc -l < $C/moved-manifests.txt) original run manifests out of the copy\"}" >> $C/commands.jsonl
  fi
  echo $pane > $C/pane.txt; echo $spane > $C/scheduler-pane.txt
  BW="bwrap --dev-bind / / --bind $P $OLD --chdir $OLD"
  herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
  herdr pane run $spane "$BW python3 tools/local_exec.py serve"
  herdr pane run $pane "$BW bash"; sleep 2
  ck() {
    $BW $REPO/.venv/bin/python $REPO/scripts/scenarios/observe.py $OLD --tools $S/dist-$host-S3u$att$variant/plugins/research-tree/tools \
      --out $C/checkpoint-$1.json >/dev/null 2>&1
    $BW $REPO/.venv/bin/python - "$OLD" "$S/dist-$host-S3u$att$variant/plugins/research-tree/tools" "$C/runs-$1.json" <<'PY' >/dev/null 2>&1
import glob, json, sys
sys.path.insert(0, sys.argv[2])
from research_db import ResearchDB
db = ResearchDB(glob.glob(f"{sys.argv[1]}/research/*/research_tree.db")[0], "ui/ui")
snap = db.export_snapshot()
runs = [{"id": r["id"], "attempt": r["attempt"], "import_record": r.get("import_record"),
         "attempts": {k: {"import_record": a.get("import_record")} for k, a in (r.get("attempts") or {}).items()}}
        for r in snap["tables"]["run"]]
json.dump({"schema_version": snap["meta"].get("schema_version"), "runs": runs,
           "evaluations": [e["id"] for e in snap["tables"]["evaluation"]],
           "reservations": [{k: r.get(k) for k in ("id", "budget_pool", "accounting_status", "actual_units")} for r in snap["tables"]["reservation"]]},
          open(sys.argv[3], "w"), default=str)
PY
    echo "[$(date +%T)] $variant checkpoint $1"
  }
  start_agent() {
    if [ $host = claude ]; then
      herdr agent start $A --kind claude --pane $pane --timeout 60000 -- --plugin-dir $S/dist-claude-S3u$att$variant/plugins/research-tree --model claude-haiku-5-5 --permission-mode auto >/dev/null 2>&1
      sleep 3; herdr agent send-keys $A down enter >/dev/null 2>&1; sleep 5
    else
      herdr agent start $A --kind codex --pane $pane --timeout 90000 -- --model gpt-6-luna -c model_reasoning_effort=medium >/dev/null 2>&1; sleep 5
    fi
  }
  if [ $host = claude ]; then CMD=/research-tree; wait_agent() { $R/waitidle.sh $A ${1:-3600} >/dev/null; }
  else
    sh scripts/setup_codex_home.sh $S/codex-home-S3u$att$variant $OLD $S/dist-codex-S3u$att$variant >/dev/null 2>&1
    herdr pane run $pane "export CODEX_HOME=$S/codex-home-S3u$att$variant"; sleep 1
    CMD='$research-tree'; wait_agent() { $R/drive_codex.sh $A $pane $C ${1:-3600} >/dev/null; }
  fi
  say() { $R/say.sh $C $A 120000 "$1" >/dev/null 2>&1; sleep 5; wait_agent ${2:-3600}; }
  ck before
  start_agent
  say "$CMD status" 900
  say "这个研究项目是用旧版 research-tree 插件建立的，插件刚升级。请按插件给出的升级与迁移流程处理：先备份研究目录，升级数据库，然后对旧记录逐项先 dry_run 再正式迁移（包括单位等缺失的元数据），再执行一次确认没有重复变更。告诉我哪些 run 的原始单位恢复了（依据是什么）、哪些仍未验证，以及 Zebra 当前的资格有没有变化。不要改动任何历史结果，也不要重新训练。" 5400
  ck migrated
  echo "{\"event\":\"end session ($variant)\"}" >> $C/commands.jsonl
  if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
  sleep 6; A=${A}r; start_agent
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，再把单位迁移以 dry_run 方式执行一次，告诉我是否还有待恢复的记录、已恢复的有没有变化。只核对。" 2400
  ck after-restart
  if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
  sleep 4; herdr pane send-keys $spane ctrl+c >/dev/null 2>&1; sleep 1
  herdr pane send-keys $pane ctrl+d >/dev/null 2>&1; herdr pane send-keys $spane ctrl+d >/dev/null 2>&1; sleep 1
  mkdir -p $C/sessions
  # the agent ran at the old project's path: only this attempt's transcripts (newer than its scenario file)
  if [ $host = claude ]; then find ~/.claude/projects/$(echo $OLD | sed 's|/|-|g') -maxdepth 1 -name "*.jsonl" -newer $C/scenario.json -exec cp {} $C/sessions/ \;
  else find $S/codex-home-S3u$att$variant/sessions -name "*.jsonl" -exec cp {} $C/sessions/ \; ; rm -f $S/codex-home-S3u$att$variant/auth.json; fi
  sha256sum $(ls $OLD/research/*/research_tree.db) > $C/old-db-after.sha256
  mkdir -p $R/archive && tar -czf $R/archive/build-S3u-$host-a$att-$variant.tar.gz -C $S dist-$host-S3u$att$variant 2>/dev/null \
    && rm -rf $S/dist-$host-S3u$att$variant $S/codex-home-S3u$att$variant
done
for p in $pane $spane; do herdr pane close $p >/dev/null 2>&1; done
echo "[$(date +%T)] done (panes closed)"
