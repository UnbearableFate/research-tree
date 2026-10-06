#!/bin/sh
# Isolated CODEX_HOME for the real-host tests of plans/design/14 §4.1: the user's login, the test model
# (gpt-6-luna, reasoning medium, 14 §5) over a copy of the user's configuration, the test project directory
# trusted, and the freshly built research-tree plugin. Delete the directory (it holds a copy of the login) after the test.
#   sh scripts/setup_codex_home.sh <codex-home> <trusted-test-dir> [<marketplace, default dist/codex>]
set -eu
home=$1
trusted=$2
market=${3:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/dist/codex}
source=${CODEX_SOURCE_HOME:-$HOME/.codex}
[ ! -e "$home" ] || { echo "$home exists; every batch uses a new CODEX_HOME" >&2; exit 2; }
[ -f "$source/auth.json" ] || { echo "no login at $source/auth.json" >&2; exit 2; }
trap 'status=$?; [ $status -eq 0 ] || rm -rf "$home"' EXIT
mkdir -p "$home"
cp "$source/auth.json" "$home/"
# The user's configuration without its model, reasoning effort, sandbox override and trusted projects: the test
# runs with Codex's default sandbox and only the test project trusted.
python3 - "$source/config.toml" "$home/config.toml" "$trusted" <<'PY'
import re, sys
src, dst, trusted = sys.argv[1:]
text = open(src).read() if __import__("os").path.exists(src) else ""
top, _, rest = text.partition("\n[")
top = "\n".join(l for l in top.splitlines() if not re.match(r"\s*(model|model_reasoning_effort|sandbox_mode)\s*=", l))
rest = ("[" + rest) if rest else ""
rest = re.sub(r'\[projects\."[^"]*"\]\n(?:[^\[\n][^\n]*\n?)*', "", rest)
open(dst, "w").write(f'model = "gpt-6-luna"\nmodel_reasoning_effort = "medium"\n{top}\n\n[projects."{trusted}"]\n'
                     f'trust_level = "trusted"\n\n{rest}')
PY
CODEX_HOME=$home codex plugin marketplace add "$market"
CODEX_HOME=$home codex plugin add research-tree@research-tree --json
