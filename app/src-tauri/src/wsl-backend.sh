# Embedded in the Windows app and sent to WSL's bash over stdin.
set -eu

port=$1
mode=$2
root=${3:-"$HOME/orrery"}
script="$root/scripts/start-cockpit.sh"
if [[ ! -f "$script" ]]; then
    printf 'ORRERY checkout not found at %s. Install ORRERY in WSL or set ORRERY_WSL_ROOT.\n' "$root" >&2
    exit 1
fi

root=$(cd -- "$root" && pwd -P)
script="$root/scripts/start-cockpit.sh"
python=${ORRERY_PYTHON:-python3}
if [[ -x "$root/bridge/.venv/bin/python" ]]; then
    python="$root/bridge/.venv/bin/python"
fi
plan=$("$python" "$root/bridge/runtime_target.py" --startup-json)
url="http://127.0.0.1:$port/telemetry/health"
if [[ "$mode" == status || "$mode" == restart || "$mode" == record ]]; then
    runtime=$("$python" -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["identity"]))' <<<"$plan")
    lifecycle="$root/bridge/backend_lifecycle.py"
    case "$mode" in
        status) exec "$python" "$lifecycle" status "$port" "$runtime" ;;
        record) exec "$python" "$lifecycle" record "$port" "$runtime" "${4:-}" ;;
    esac
    result=$("$python" "$lifecycle" stop "$port" "$runtime" "${4:-}" "${5:-}" "${6:-}")
    printf '%s\0' "$result"
    state=$("$python" -c 'import json,sys; print(json.load(sys.stdin)["state"])' <<<"$result")
    if [[ "$state" != stopped ]]; then exit 0; fi
fi
health() {
    local response
    response=$(curl --noproxy '*' --fail --silent --max-time 3 "$url") || return 1
    printf '%s\0%s\0%s' "$plan" "$root" "$response"
}

if health; then
    exit 0
fi
if [[ "$mode" == probe ]]; then
    printf 'Windows port %s is occupied and does not reach the selected WSL cockpit. Set ORRERY_WSL_PORT to a free port.\n' "$port" >&2
    exit 1
fi

# A dedicated tmux session keeps the cockpit available after the window closes.
# Agents continue to use their regular tmux server.
umask 077
state_dir="${XDG_STATE_HOME:-"$HOME/.local/state"}/orrery"
mkdir -p -- "$state_dir"
log="$state_dir/windows-cockpit-$port.log"
session="cockpit-$port"
ctmux() { env -u TMUX -u TMUX_PANE tmux -L orrery-app "$@"; }

if [[ "$mode" == restart ]]; then
    # Stopping the verified backend also lets its old wrapper exit. Preserve
    # both the ordinary agent server and any other cockpit session.
    stop_deadline=$((SECONDS + 5))
    while ctmux has-session -t "=$session" 2>/dev/null; do
        if health; then exit 0; fi
        if (( SECONDS >= stop_deadline )); then
            printf 'The previous WSL cockpit launcher did not exit.\n' >&2
            exit 1
        fi
        sleep 0.25
    done
fi

if ! ctmux has-session -t "=$session" 2>/dev/null; then
    # The second check also covers two app launches racing to create a session.
    # tmux injects its own TMUX and TMUX_PANE into the new process.
    ctmux new-session -d -s "$session" env -u TMUX -u TMUX_PANE \
        PORT="$port" HOST=127.0.0.1 ORRERY_NO_UPDATE_CHECK=1 \
        bash -c 'exec bash "$1" >> "$2" 2>&1' bash "$script" "$log" ||
        ctmux has-session -t "=$session"
fi

deadline=$((SECONDS + 40))
while ctmux has-session -t "=$session" 2>/dev/null && (( SECONDS < deadline )); do
    if health; then
        exit 0
    fi
    sleep 0.5
done
if health; then
    exit 0
fi
printf 'WSL cockpit did not start on port %s. See %s in WSL. If the port is occupied, set ORRERY_WSL_PORT to a free port.\n' "$port" "$log" >&2
exit 1
