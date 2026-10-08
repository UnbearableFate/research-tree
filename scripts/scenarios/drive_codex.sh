#!/bin/bash
# drive_codex.sh <agent> <pane> <ctl> <max-seconds>: wait for the agent; approve only the research_tree MCP tool
# prompts ("Always allow"), log each approval; stop at idle or at any other blocked dialog (returned for review).
a=$1; pane=$2; ctl=$3; max=${4:-3600}; t=0
while [ $t -lt $max ]; do
  s=$(/home/yu/workspace/rt-scenarios/waitidle.sh "$a" $((max - t)))
  screen=$(herdr pane read "$pane" --source visible --lines 60)
  if [ "$s" = "idle" ] && echo "$screen" | grep -q 'Hooks need review\|Set up Advanced Account Security\|Would you like to run\|Allow the research_tree MCP'; then s=blocked; fi
  if [ "$s" = "blocked" ]; then
    if echo "$screen" | grep -q 'Hooks need review' && echo "$screen" | grep -q 'Trust all and continue'; then
      echo '{"event":"trusted plugin hooks (option 2) as the README instructs"}' >> "$ctl/commands.jsonl"
      herdr agent send-keys "$a" down enter >/dev/null; sleep 3; t=$((t+3)); continue
    fi
    if echo "$screen" | grep -q 'Set up Advanced Account Security'; then
      herdr agent send-keys "$a" esc >/dev/null; sleep 2; t=$((t+2)); continue
    fi
    if echo "$screen" | grep -q 'Allow the research_tree MCP server to run tool'; then
      tool=$(echo "$screen" | grep -o 'run tool "[a-z_]*"' | head -1)
      python3 -c 'import json,sys,datetime; print(json.dumps({"ts":datetime.datetime.now(datetime.UTC).isoformat(),"event":"approval","what":sys.argv[1],"choice":"Always allow"}))' "$tool" >> "$ctl/commands.jsonl"
      herdr agent send-keys "$a" 3 >/dev/null; sleep 3; t=$((t+3)); continue
    fi
    if echo "$screen" | grep -q "don't ask again for commands that start with" && echo "$screen" | tr -d '\n ' | grep -q "plugins/cache/research-tree/research-tree/0.1.0/tools/"; then
      cmd=$(echo "$screen" | grep -A3 '^\s*\$' | tr -s ' ' | head -4 | tr '\n' ' ')
      python3 -c 'import json,sys,datetime; print(json.dumps({"ts":datetime.datetime.now(datetime.UTC).isoformat(),"event":"approval","what":sys.argv[1],"choice":"p (plugin tool, do not ask again)"}))' "$cmd" >> "$ctl/commands.jsonl"
      herdr agent send-keys "$a" p >/dev/null; sleep 3; t=$((t+3)); continue
    fi
    echo "blocked-other"; exit 0
  fi
  echo "$s"; exit 0
done
echo timeout
