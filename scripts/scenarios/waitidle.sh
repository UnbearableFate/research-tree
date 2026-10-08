#!/bin/bash
# waitidle.sh <agent> <max-seconds>: until the agent is idle/done/blocked for two consecutive checks
a=$1; max=${2:-3600}; n=0; ok=0
while [ $n -lt $max ]; do
  s=$(herdr agent get "$a" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['agent']['agent_status'])" 2>/dev/null)
  case "$s" in idle|done|blocked) ok=$((ok+1));; *) ok=0;; esac
  [ $ok -ge 2 ] && { echo "$s"; exit 0; }
  sleep 5; n=$((n+5))
done
echo "timeout:$s"
