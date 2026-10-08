#!/bin/sh
# Prepare a directory for a research-tree project, without Python: make it a uv project with the tools'
# dependencies, then copy the plan template (plan.md) and the default configuration (research-tree.yaml) for
# the user to fill in. Files already there are kept. Next step: init.
set -eu

usage='Usage: sh prepare.sh [--python 3.13] [--update-uv] [project-directory]'
plugin_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dependencies='latticedb==0.15.0 jsonschema>=4.26 pyyaml>=6.0 pypdf>=5.1'
python=3.13
update_uv=false
destination=.
named=false
while [ "$#" -gt 0 ]; do
    case $1 in
        --python=*) python=${1#--python=} ;;
        --python)
            [ "$#" -ge 2 ] || { printf '%s\n' "$usage" >&2; exit 2; }
            python=$2
            shift ;;
        --update-uv) update_uv=true ;;
        -*) printf '%s\n' "$usage" >&2; exit 2 ;;
        *)
            if $named; then printf '%s\n' "$usage" >&2; exit 2; fi
            destination=$1
            named=true ;;
    esac
    shift
done
if [ -z "$python" ]; then
    printf '%s\n' "$usage" >&2
    exit 2
fi
cd -- "$destination"

if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' '需要 uv，但当前环境找不到它。安装：curl -LsSf https://astral.sh/uv/install.sh | sh，然后重开会话。' >&2
    exit 1
fi
printf 'uv：%s\n' "$(uv --version)"
if $update_uv; then
    if output=$(uv self update 2>&1); then
        printf '%s\n' 'uv self update：完成'
    else
        printf 'uv self update 未成功（继续）：%s\n' "$(printf '%s' "$output" | tail -n 3)"
    fi
fi
if [ -e pyproject.toml ]; then
    printf '%s\n' '已有 pyproject.toml：沿用现有 uv 项目，跳过 uv init。'
else
    # Standalone even inside another uv project, so this directory gets its own .venv.
    if ! output=$(uv init . --no-workspace --python="$python" 2>&1); then
        printf 'uv init . --no-workspace --python=%s 失败：%s\n' "$python" "$(printf '%s' "$output" | tail -n 3)" >&2
        exit 1
    fi
    printf 'uv init . --no-workspace --python=%s：完成\n' "$python"
fi
# shellcheck disable=SC2086  # the dependency list is meant to split into words
if ! output=$(uv add --project . $dependencies 2>&1); then
    printf 'uv add %s 失败：%s\n' "$dependencies" "$(printf '%s' "$output" | tail -n 3)" >&2
    exit 1
fi
printf 'uv add %s：完成\n' "$dependencies"

copy() {  # template, target, what it is
    if [ -e "$2" ] || [ -L "$2" ]; then
        printf '保留已有的%s：%s\n' "$3" "$2"
    # noclobber also protects against a file created after the check above.
    elif (set -C; cat "$plugin_root/schema/$1" > "$2") 2>/dev/null; then
        printf '已生成%s：%s\n' "$3" "$2"
    else
        printf '无法生成%s：%s\n' "$3" "$2" >&2
        exit 1
    fi
}
copy plan.template.md plan.md 研究计划
copy config.template.yaml research-tree.yaml 项目配置
printf '%s\n' '下一步：填写 plan.md（研究目标与初始假说必填），按需修改 research-tree.yaml，然后运行 init。'
