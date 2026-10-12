# Read the existing generated environment; never persist a second mode record.
orrery_runtime_value() (
  [ -r "${AGENTSTACK_HOME:-${HOME}/.agentstack}/env.sh" ] || return 0
  . "${AGENTSTACK_HOME:-${HOME}/.agentstack}/env.sh" >/dev/null 2>&1 || return 1
  eval "printf '%s' \"\${$1:-}\""
)
orrery_load_runtime() {
  AGENTSTACK_RUNTIME_MODE="${AGENTSTACK_RUNTIME_MODE:-$(orrery_runtime_value AGENTSTACK_RUNTIME_MODE)}"
  case "${AGENTSTACK_RUNTIME_MODE:-legacy}" in
    legacy | '') return 0 ;;
    global)
      AGENTSTACK_HOME="${AGENTSTACK_HOME:-${HOME}/.agentstack}"
      AGENTSTACK_GLOBAL_SERVER_CONFIG="${AGENTSTACK_GLOBAL_SERVER_CONFIG:-$(orrery_runtime_value AGENTSTACK_GLOBAL_SERVER_CONFIG)}"
      if [ -z "$AGENTSTACK_GLOBAL_SERVER_CONFIG" ]; then
        printf '%s\n' 'COCKPIT_GLOBAL_CONFIG_REQUIRED: restore the explicit server config; no legacy fallback.' >&2
        return 2
      fi
      export AGENTSTACK_RUNTIME_MODE AGENTSTACK_HOME AGENTSTACK_GLOBAL_SERVER_CONFIG
      ;;
    *) printf '%s\n' 'RUNTIME_MODE_INVALID' >&2; return 2 ;;
  esac
}
