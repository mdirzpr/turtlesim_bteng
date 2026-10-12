#!/usr/bin/env bash
################################################################################
# 🐢 run.sh — one-command runner for the Turtlesim BTEng demo (the lazy path)
#
# This is a convenience wrapper, NOT a replacement for the documented workflow.
# Everything it does is the same handful of commands from README.md /
# docs/USAGE.md — docker compose build, colcon build, ros2 launch — just
# checked, chained and defaulted for you.
#
#   ./run.sh                 # doctor → image → workspace → launch (sequential)
#   ./run.sh closest         # same, closest-first strategy
#   ./run.sh help            # all subcommands
#
# Nothing here is magic: run `./run.sh --dry-run <cmd>` to print the underlying
# commands instead of executing them.
################################################################################

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

IMAGE="turtlesim_bteng:dev"
SERVICE="dev"
VENV="$REPO_ROOT/.venv"
REQUIREMENTS="$REPO_ROOT/tools/requirements.txt"
REQ_STAMP="$VENV/.requirements.sha256"
WS_SETUP="$REPO_ROOT/.colcon/install/setup.bash"
DRY_RUN=0

# ─── pretty output ────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
  BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; NC=''
fi

info()  { echo -e "${BLUE}ℹ️  $*${NC}"; }
ok()    { echo -e "${GREEN}✅ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}" >&2; }
die()   { echo -e "${RED}❌ $*${NC}" >&2; exit 1; }
step()  { echo; echo -e "${BOLD}${BLUE}━━ $* ━━${NC}"; }

# Echo a command (shell-quoted, so it is copy-pasteable), then run it — or only
# echo it under --dry-run.
run() {
  local arg shown=()
  for arg in "$@"; do
    [[ "$arg" == *[[:space:]]* ]] && shown+=("\"$arg\"") || shown+=("$arg")
  done
  echo -e "${BOLD}\$ ${shown[*]}${NC}"
  [[ $DRY_RUN -eq 1 ]] && return 0
  "$@"
}

# docker compose with host UID/GID passed through, matching docker-compose.yaml's
# ${UID}/${GID} build args. `env` is used because bash's $UID is readonly.
dc() {
  run env UID="$(id -u)" GID="$(id -g)" docker compose "$@"
}

# ─── prerequisite checks ──────────────────────────────────────────────────────
check_docker() {
  command -v docker >/dev/null 2>&1 \
    || die "docker not found. Install Docker Engine 20.10+ — https://docs.docker.com/engine/install/"
  docker compose version >/dev/null 2>&1 \
    || die "'docker compose' (Compose V2) not available. Install the docker-compose-plugin."
  docker info >/dev/null 2>&1 \
    || die "The Docker daemon is not reachable. Start it (sudo systemctl start docker) or add yourself to the 'docker' group."
  ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null) + compose $(docker compose version --short 2>/dev/null)"
}

# turtlesim needs an X server; the container draws onto the host display.
# $1 = "report" to only report the state (doctor), anything else to fix it.
check_x11() {
  local mode="${1:-fix}"
  if [[ -z "${DISPLAY:-}" ]]; then
    warn "DISPLAY is not set — the turtlesim window will not open (the BT console log still works)."
    return 0
  fi
  if ! command -v xhost >/dev/null 2>&1; then
    warn "xhost not found — if no turtlesim window appears, allow X11 access for docker manually."
    return 0
  fi
  if xhost 2>/dev/null | grep -q '^LOCAL:$'; then
    ok "X11 access for local containers granted (DISPLAY=$DISPLAY)"
  elif [[ "$mode" == "report" ]]; then
    warn "X11 access for local containers not granted — running the demo will do 'xhost +local:docker' for you."
  else
    info "Granting local containers X11 access (xhost +local:docker)"
    run xhost +local:docker >/dev/null \
      || warn "xhost failed — run 'xhost +local:docker' yourself if no window appears."
  fi
}

# ─── host virtualenv (for the tools/ viewers only) ────────────────────────────
ensure_venv() {
  if [[ ! -x "$VENV/bin/python" ]]; then
    step "Creating host virtualenv (.venv)"
    command -v python3 >/dev/null 2>&1 || die "python3 not found — needed for the tools/ viewers."
    if ! run python3 -m venv "$VENV"; then
      die "Failed to create .venv. On Debian/Ubuntu: sudo apt install python3-venv"
    fi
    [[ $DRY_RUN -eq 1 ]] || run "$VENV/bin/python" -m pip install --quiet --upgrade pip
    ok "Created $VENV"
  fi

  # Reinstall only when tools/requirements.txt changed since the last install.
  local want have=""
  want="$(sha256sum "$REQUIREMENTS" | cut -d' ' -f1)"
  [[ -f "$REQ_STAMP" ]] && have="$(cat "$REQ_STAMP")"
  if [[ "$want" != "$have" ]]; then
    step "Installing host tool requirements"
    run "$VENV/bin/python" -m pip install --quiet -r "$REQUIREMENTS"
    [[ $DRY_RUN -eq 1 ]] || echo "$want" > "$REQ_STAMP"
    ok "Installed: $(grep -v '^\s*#' "$REQUIREMENTS" | grep -v '^\s*$' | awk '{print $1}' | tr '\n' ' ')"
  else
    ok "Host tool requirements already satisfied (.venv)"
  fi
}

# ─── docker image + colcon workspace ──────────────────────────────────────────
image_exists() { docker image inspect "$IMAGE" >/dev/null 2>&1; }

ensure_image() {
  if image_exists && [[ "${FORCE_IMAGE:-0}" -eq 0 ]]; then
    ok "Docker image $IMAGE present"
  else
    step "Building the Docker image ($IMAGE)"
    dc build
    ok "Image built"
  fi
}

# True when the workspace has never been built, or a source file is newer than
# the last install/setup.bash — same rule you'd apply by hand.
workspace_stale() {
  [[ -f "$WS_SETUP" ]] || return 0
  local newer
  newer="$(find interfaces bt_turtlesim_ctrl \
             -type f \( -name '*.py' -o -name '*.xml' -o -name '*.msg' -o -name '*.yaml' \
                        -o -name '*.txt' -o -name '*.cfg' \) \
             -newer "$WS_SETUP" -print -quit 2>/dev/null)"
  [[ -n "$newer" ]]
}

ensure_workspace() {
  if [[ "${FORCE_BUILD:-0}" -eq 0 ]] && ! workspace_stale; then
    ok "colcon workspace up to date (.colcon/install)"
    return 0
  fi
  step "Building the ROS 2 workspace (colcon build --symlink-install)"
  # The entrypoint sources ROS 2 before exec'ing this command.
  dc run --rm "$SERVICE" bash -c "cd /dev_ws && colcon build --symlink-install"
  ok "Workspace built"
}

# ─── subcommands ──────────────────────────────────────────────────────────────
cmd_doctor() {
  step "Checking prerequisites"
  check_docker
  check_x11 report
  if image_exists; then ok "Docker image $IMAGE present"
  else warn "Docker image $IMAGE missing — './run.sh build' will create it."; fi
  if [[ -f "$WS_SETUP" ]]; then
    workspace_stale && warn "colcon workspace is stale (sources changed) — will rebuild on next run." \
                    || ok "colcon workspace built and up to date"
  else
    warn "colcon workspace not built yet — './run.sh build' will build it."
  fi
  if [[ -x "$VENV/bin/python" ]]; then ok "Host .venv present ($("$VENV/bin/python" --version))"
  else warn "Host .venv missing — './run.sh setup' creates it (only needed for the viewers)."; fi
  echo
  info "Nothing above is fatal except a missing/stopped Docker."
}

cmd_setup() {
  step "Setting up everything (host venv + image + workspace)"
  ensure_venv
  check_docker
  ensure_image
  ensure_workspace
  echo
  ok "Ready. Run './run.sh' to launch the demo."
}

# Launch the demo. Bare 'sequential'/'closest' become strategy:=…; anything else
# (e.g. min_interval:=1.0) is passed through to ros2 launch untouched.
cmd_demo() {
  local launch_args=()
  local arg
  for arg in "$@"; do
    case "$arg" in
      sequential|closest) launch_args+=("strategy:=$arg") ;;
      *) launch_args+=("$arg") ;;
    esac
  done
  [[ ${#launch_args[@]} -eq 0 ]] && launch_args=("strategy:=sequential")

  check_docker
  check_x11
  ensure_image
  ensure_workspace

  step "Launching the demo"
  info "Live BT stream on tcp://localhost:2667 — run './run.sh tree' in another terminal."
  info "Stop with Ctrl-C."
  dc run --rm "$SERVICE" bash -c \
    "ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py ${launch_args[*]}"
}

cmd_shell() {
  check_docker
  check_x11
  ensure_image
  step "Opening a dev shell in the container"
  info "Inside: cd /dev_ws && colcon build --symlink-install && ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py"
  dc run --rm "$SERVICE" bash
}

cmd_build() {
  check_docker
  ensure_image
  FORCE_BUILD=1 ensure_workspace
}

# Full rebuild — use after Dockerfile / entrypoint.sh changes, which a plain
# 'build' does not pick up (it reuses an existing image).
cmd_rebuild() {
  check_docker
  FORCE_IMAGE=1 ensure_image
  FORCE_BUILD=1 ensure_workspace
}

cmd_viewer() { ensure_venv; step "BTEng tick log (Ctrl-C to quit)"; run "$VENV/bin/python" tools/bt_zmq_viewer.py "$@"; }

# Is something already publishing the BTEng stream on the host?
demo_running() { (echo >/dev/tcp/127.0.0.1/2667) 2>/dev/null; }

# 'tree' = one-terminal experience: if no demo is running, start it in the
# background (turtlesim window opens, its logs go to .colcon/demo.log) and show
# only the live tree here. Ctrl-C quits the viewer and stops that demo. If a demo
# is already running (e.g. started with './run.sh closest' elsewhere), just view.
cmd_tree() {
  local args=() launch_args=() arg started=0
  for arg in "$@"; do
    case "$arg" in
      sequential|closest) args+=(--strategy "$arg"); launch_args+=("$arg") ;;
      *:=*) launch_args+=("$arg") ;;
      *) args+=("$arg") ;;
    esac
  done
  ensure_venv

  local log="$REPO_ROOT/.colcon/demo.log" name="turtlesim_bteng_demo"
  if [[ $DRY_RUN -eq 0 ]] && demo_running; then
    info "Demo already running on :2667 — attaching the viewer only."
  else
    check_docker
    check_x11
    ensure_image
    ensure_workspace
    [[ ${#launch_args[@]} -eq 0 ]] && launch_args=("sequential")
    local ros_args=() a
    for a in "${launch_args[@]}"; do
      case "$a" in sequential|closest) ros_args+=("strategy:=$a") ;; *) ros_args+=("$a") ;; esac
    done
    step "Starting the demo in the background (logs: ${log#$REPO_ROOT/})"
    mkdir -p "$(dirname "$log")"
    if [[ $DRY_RUN -eq 1 ]]; then
      dc run --rm -T --name "$name" "$SERVICE" bash -c \
        "ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py ${ros_args[*]}"
    else
      dc run --rm -T --name "$name" "$SERVICE" bash -c \
        "ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py ${ros_args[*]}" >"$log" 2>&1 &
      started=1
      trap 'docker stop "'"$name"'" >/dev/null 2>&1 || true' EXIT
      trap 'exit 130' INT TERM
    fi
  fi

  step "BTEng live tree view (Ctrl-C to quit)"
  # No 'set -e' abort on Ctrl-C so the EXIT trap can stop the demo.
  run "$VENV/bin/python" tools/bt_tree_viewer.py "${args[@]+"${args[@]}"}" || true
  if [[ $started -eq 1 ]]; then info "Stopping the demo…"; fi
}

cmd_stop() { check_docker; step "Stopping containers"; dc down; ok "Stopped"; }

cmd_clean() {
  step "Cleaning colcon build artifacts (.colcon/build, install, log)"
  run rm -rf .colcon/build .colcon/install .colcon/log
  run mkdir -p .colcon/build .colcon/install .colcon/log
  ok "Cleaned — the next run rebuilds the workspace."
  info "The Docker image and .venv are untouched (docker image rm $IMAGE / rm -rf .venv to drop those)."
}

cmd_help() {
  cat <<EOF
${BOLD}🐢 run.sh — one-command runner for the Turtlesim BTEng demo${NC}

${BOLD}USAGE${NC}
  ./run.sh [--dry-run] [command] [args…]

${BOLD}COMMANDS${NC}
  ${GREEN}demo${NC} [strategy|args…]   Build what's missing, then launch the demo (default command).
                         'sequential' / 'closest' are shorthand for strategy:=…;
                         any other arg is passed straight to ros2 launch.
  ${GREEN}setup${NC}                  Prepare everything up front: .venv, image, workspace.
  ${GREEN}build${NC}                  Build the Docker image (if missing) and force a colcon rebuild.
  ${GREEN}rebuild${NC}                Rebuild the image from scratch too — needed after changes to
                         docker/Dockerfile or docker/entrypoint.sh.
  ${GREEN}shell${NC}                  Open an interactive dev shell inside the container.
  ${GREEN}tree${NC} [strategy|args…]  Start the demo (turtlesim window) in the background and show only the live
                         BT tree here; Ctrl-C stops both. Attaches only if a demo is already running.
  ${GREEN}viewer${NC} [args…]         Flat live tick log on the host (tools/bt_zmq_viewer.py).
  ${GREEN}doctor${NC}                 Check docker, X11, image, workspace and .venv — changes nothing.
  ${GREEN}stop${NC}                   docker compose down.
  ${GREEN}clean${NC}                  Remove colcon build artifacts (.colcon/*).
  ${GREEN}help${NC}                   This message.

${BOLD}OPTIONS${NC}
  --dry-run              Print the underlying commands instead of running them.

${BOLD}EXAMPLES${NC}
  ./run.sh                              # sequential (FIFO) hunt
  ./run.sh closest                      # closest-first hunt
  ./run.sh demo closest min_interval:=1.0 max_interval:=2.0
  ./run.sh demo enable_zmq:=false
  ./run.sh tree closest                 # window + live tree only, logs in .colcon/demo.log

${BOLD}NOTE${NC}
  This wrapper only chains the documented commands (docker compose build,
  colcon build --symlink-install, ros2 launch …). The manual workflow in
  README.md / docs/USAGE.md remains fully supported — use it whenever you want
  control over the individual steps.
EOF
}

# ─── argument dispatch ────────────────────────────────────────────────────────
main() {
  while [[ ${1:-} == --* ]]; do
    case "$1" in
      --dry-run) DRY_RUN=1; shift ;;
      --help) cmd_help; return 0 ;;
      *) die "Unknown option: $1  (see ./run.sh help)" ;;
    esac
  done

  local cmd="${1:-demo}"
  (( $# > 0 )) && shift          # remaining "$@" are the subcommand's own args

  case "$cmd" in
    demo)                 cmd_demo "$@" ;;
    sequential|closest)   cmd_demo "$cmd" "$@" ;;   # ./run.sh closest
    *:=*)                 cmd_demo "$cmd" "$@" ;;   # ./run.sh min_interval:=1.0
    setup)                cmd_setup ;;
    build)                cmd_build ;;
    rebuild)              cmd_rebuild ;;
    shell|bash)           cmd_shell ;;
    tree|watch)           cmd_tree "$@" ;;
    viewer|log)           cmd_viewer "$@" ;;
    doctor|check)         cmd_doctor ;;
    stop|down)            cmd_stop ;;
    clean)                cmd_clean ;;
    help|-h|--help)       cmd_help ;;
    *) die "Unknown command: $cmd  (see ./run.sh help)" ;;
  esac
}

main "$@"
