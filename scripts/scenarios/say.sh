#!/bin/bash
# say.sh <ctl-dir> <agent> <timeout-ms> <text> : submit a user prompt through herdr and log it
ctl=$1; agent=$2; to=$3; shift 3; text="$*"
python3 -c 'import json,sys,datetime; print(json.dumps({"ts":datetime.datetime.utcnow().isoformat()+"Z","agent":sys.argv[1],"prompt":sys.argv[2]},ensure_ascii=False))' "$agent" "$text" >> "$ctl/commands.jsonl"
herdr agent prompt "$agent" "$text" --wait --timeout "$to" 2>&1 | tail -c 300
echo
herdr agent get "$agent" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['agent']['agent_status'])"
