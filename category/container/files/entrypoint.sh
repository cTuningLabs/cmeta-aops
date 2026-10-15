#!/bin/sh
# cMeta container entrypoint (rendered from the "{{cmeta.template_alias}}" template).
#  1. every cMeta repository mounted under $HOME/repos/<alias> (cx container run --repo=<host path>) or under
#     $HOME/data/<alias> (a data repository of the orchestrator, get-host--docker) is plugged in, so the same image
#     serves any set of repositories, including private ones, without a build-time secret;
#  2. CMETA_CONFIG_FROM_ENV="cfg.key=ENV_VAR;..." stores run-time secrets in local config artifacts
#     (cx config set <cfg> --meta.<key>=$ENV_VAR) - the image itself never contains them;
#  3. CMETA_REINDEX=1 rebuilds the index, then the command runs;
#  4. $HOME/.cmeta-ready says the steps above are done (get-host--docker waits for it before the first run inside).
set -e
export CMETA_HOME="${CMETA_HOME:-$HOME/CMETA}"
export PATH="$HOME/.local/bin:$PATH"
rm -f "$HOME/.cmeta-ready"

for d in "$HOME"/repos/*/ "$HOME"/data/*/; do
  [ -d "$d" ] || continue
  if [ -f "$d/_cmr.yaml" ] || [ -f "$d/_cmr.json" ]; then
    cx repo plug "$d" >/dev/null 2>&1 || true
  fi
done

if [ -n "$CMETA_CONFIG_FROM_ENV" ]; then
  printf '%s' "$CMETA_CONFIG_FROM_ENV" | tr ';' '\n' | while IFS='=' read -r key var; do
    [ -n "$key" ] && [ -n "$var" ] || continue
    cfg="${key%%.*}"; k="${key#*.}"
    val="$(printenv "$var" 2>/dev/null || true)"
    [ -n "$val" ] && cx config set "$cfg" --meta."$k"="$val" >/dev/null 2>&1 || true
  done
fi

[ -n "$CMETA_REINDEX" ] && cx --reindex >/dev/null 2>&1 || true
: > "$HOME/.cmeta-ready"

exec "$@"
