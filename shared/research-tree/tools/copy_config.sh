#!/bin/sh
# Copy the shared default verbatim, without Python, uv or an initialized project.
set -eu

plugin_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
destination=${1:-.}
target="$destination/research-tree.yaml"

if [ "$#" -gt 1 ]; then
    printf '%s\n' 'Usage: sh copy_config.sh [project-directory]' >&2
    exit 2
fi
if [ -e "$target" ] || [ -L "$target" ]; then
    printf '保留已有配置，未覆盖：%s\n' "$target" >&2
    exit 1
fi
# noclobber also protects against a file created after the check above.
if ! (set -C; cat "$plugin_root/schema/config.template.yaml" > "$target"); then
    printf '无法复制默认配置：%s\n' "$target" >&2
    exit 1
fi
printf '已复制默认配置：%s\n编辑后初始化时使用 init <计划.md> --config research-tree.yaml。\n' "$target"
