#!/bin/bash
# sandbox.sh <private-dir> <workspace> -- <command...>
# Run the agent (or its scheduler and training jobs) where the private material cannot be read (§11.4): the whole
# file system read-only except the workspace and the user's tool state, the private directory replaced by an empty
# tmpfs, the Docker sockets replaced by /dev/null (docker group membership would otherwise reach any file), a new
# PID namespace with its own /proc (no other process's environment or command line), a new session (no terminal
# injection), and the sandbox ends with its parent. The evaluator runs outside.
set -eu
private=$(readlink -f "$1"); work=$(readlink -f "$2"); shift 2
[ "${1:-}" = "--" ] && shift
args=(--ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-pid --unshare-ipc --new-session
      --die-with-parent --bind "$work" "$work" --tmpfs "$private")
# Bound at their resolved paths: bwrap cannot mount onto a symlink (a home whose tool state lives elsewhere), and
# the link itself, inside the read-only root, then leads to the writable bind.
for d in "$HOME/.claude" "$HOME/.claude.json" "$HOME/.codex" "$HOME/.cache" "$HOME/.local/share/uv" "$HOME/.config"; do
  [ -e "$d" ] && { r=$(readlink -f "$d"); args+=(--bind "$r" "$r"); }
done
for s in $(for x in /var/run/docker.sock /run/docker.sock /run/user/$(id -u)/docker.sock; do [ -e "$x" ] && readlink -f "$x"; done | sort -u); do
  args+=(--ro-bind /dev/null "$s")
done
exec bwrap "${args[@]}" --chdir "$work" "$@"
