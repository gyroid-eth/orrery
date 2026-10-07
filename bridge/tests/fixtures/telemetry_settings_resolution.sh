# Setting resolver from gyroid-eth/orrery-telemetry
# a4e51b08847e955bc12d1c360f9eb65a9261ab6c/scripts/install.sh
# Kept verbatim; our tests provide the installed-env reader and entry values.
SETTINGS_ENV_FILE="$INSTALL_DIR/env.sh"
CHOSEN_SETTINGS=""
SETTING_SOURCE=""
PREVIOUS_CHOSEN=""
PREVIOUS_CHOSEN_RECORDED=false
if [[ -f "$SETTINGS_ENV_FILE" ]] && grep -q '^export AGENTSTACK_CHOSEN_SETTINGS=' "$SETTINGS_ENV_FILE"; then
  PREVIOUS_CHOSEN_RECORDED=true
  PREVIOUS_CHOSEN="$(agentstack_installed_env_value AGENTSTACK_CHOSEN_SETTINGS "$SETTINGS_ENV_FILE")"
fi

setting_listed() {
  case " $2 " in *" $1 "*) return 0 ;; esac
  return 1
}

setting_previously_chosen() {
  local name="$1" saved="$2" default="$3"
  if [[ "$PREVIOUS_CHOSEN_RECORDED" == true ]]; then
    setting_listed "$name" "$PREVIOUS_CHOSEN"
    return
  fi
  case "$name" in
    AGENTSTACK_PATH|AGENTSTACK_PYTHON) return 1 ;;
  esac
  [[ "$saved" != "$default" ]]
}

# resolve_setting VAR NAME DEFAULT [MODE [ENV_NAME]]
#   VAR holds the explicit value on entry (from ENV_NAME, default NAME, or an
#   option) and the value in effect on return; SETTING_SOURCE says which of
#   explicit / saved / default it is. MODE `kept` inherits the saved value even
#   under --reset-settings and whether or not it was chosen; `found` inherits
#   it, chosen or not, unless reset (a location the installer found itself).
resolve_setting() {
  local var="$1" name="$2" default="${3:-}" mode="${4:-chosen}" env_name="${5:-$2}"
  local value="${!1:-}" saved given=""
  saved="$(agentstack_installed_env_value "$name" "$SETTINGS_ENV_FILE")"
  if setting_listed "$env_name" "$OPTION_GIVEN"; then
    given=option
  elif [[ -n "${!env_name+x}" ]]; then
    given=environment
    # Only against a record of choices: before it, a value someone passes on
    # every install looks the same as an echo, and taking it for one sent it
    # back to the default and flipped it on the next install (#146, N-1).
    if [[ "$PREVIOUS_CHOSEN_RECORDED" == true && -n "$saved" && "$value" == "$saved" ]]; then
      given=""
    fi
  fi
  if [[ -n "$given" ]]; then
    if [[ -n "$value" ]]; then
      SETTING_SOURCE=explicit
      CHOSEN_SETTINGS="${CHOSEN_SETTINGS:+$CHOSEN_SETTINGS }$name"
    else
      value="$default"
      SETTING_SOURCE=default
    fi
  elif [[ -n "$saved" ]] && {
    [[ "$mode" == kept ]] ||
      { [[ "$RESET_SETTINGS" != 1 ]] &&
        { [[ "$mode" == found ]] || setting_previously_chosen "$name" "$saved" "$default"; }; }
  }; then
    value="$saved"
    SETTING_SOURCE=saved
    # Kept or found without being chosen stays unchosen in the record.
    if [[ "$mode" == chosen ]] || setting_previously_chosen "$name" "$saved" "$default"; then
      CHOSEN_SETTINGS="${CHOSEN_SETTINGS:+$CHOSEN_SETTINGS }$name"
    fi
  else
    value="$default"
    SETTING_SOURCE=default
  fi
  printf -v "$var" '%s' "$value"
}
# --- end setting resolution ---
