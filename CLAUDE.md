# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A ROS 2 Jazzy port of the turtlesim prey-hunting demo from **BehaviorTree.CPP**
to **BTEng** (pure-Python behavior trees) + **bteng-ros2**. Two packages:

1. **`bt_turtlesim_ctrl`** (ament_**python**) — turtlesim prey-hunting demo. A
   spawner node drops prey turtles every 2–4 s; the BT controller drives
   `turtle1` to catch and eliminate them. Two hunting strategies are selectable
   at launch time. Live introspection via BTEng's **ZmqPublisher on port 2667**
   plus a colored console Logger. **No Groot2** (incompatible with BTEng's stream).

2. **`bt_turtlesim_interfaces`** (ament_**cmake**) — custom ROS 2 message
   (`TurtleTarget.msg`) shared between the spawner and controller. Unchanged
   from the C++ version.

BTEng (`bteng`) and `bteng-ros2` are installed **via pip**, not built from
source — there is no vcstool/colcon source build of them.

## Development Environment

All development happens inside a Docker container. Source packages are
bind-mounted under `/dev_ws/src/`.

```bash
# Build the Docker image (only needed once or after Dockerfile changes)
docker compose build

# Start an interactive dev shell
docker compose run --rm dev bash

# Inside container — build the full workspace
# (interfaces build first; bt_turtlesim_ctrl depends on it)
cd /dev_ws && colcon build --symlink-install
source install/setup.bash

# Build a single package
colcon build --symlink-install --packages-select bt_turtlesim_ctrl
```

## Running

```bash
# Sequential strategy — catch turtles in the order they appeared (FIFO)
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py

# Closest-first strategy — always chase the nearest prey
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py strategy:=closest
```

`./run.sh` (repo root) is an optional host-side wrapper over the same commands:
it checks docker/X11, builds the image when missing, runs `colcon build` when
`.colcon/install/setup.bash` is older than a source file, then launches
(`./run.sh`, `./run.sh closest`, `./run.sh shell`, `./run.sh tree`,
`./run.sh doctor`, `./run.sh --dry-run …`). It adds no behavior of its own — the
documented manual flow stays the reference. Host-side viewer deps live in
`tools/requirements.txt` and are installed into `.venv` on first use.

The controller streams live tick events over BTEng's `ZmqPublisher` on
`tcp://*:2667` (when `bteng[zmq]` / pyzmq is installed) and always logs the tree
status to the console with the colored `Logger` sink.

## Architecture

### bt_turtlesim_ctrl architecture

`turtle_controller_node.py` is the BT executor entry point. It subclasses
bteng-ros2's `RosBTExecutor` to reuse ros_node injection and clock wiring, then:

1. Declares ROS parameters and seeds the shared `Blackboard`.
2. Loads the strategy XML with BTEng's **`XMLTreeParser`** (`parse_file`) and
   wraps it in a `Tree(TreeMetadata(...), root, blackboard)`.
3. Calls `set_tree(tree)` — this injects `ros_node=self` into **every** tree node
   (deferred injection; nodes are constructed by the factory with no ros_node),
   wires the ROS clock, and runs `tree.validate()`.
4. Attaches an `Inspector` + `Logger` (colored console sink) and, if enabled, a
   `ZmqPublisher(port=zmq_port)` on the inspector.
5. Subscribes to `/turtle1/pose` (→ `main_x/y/theta`) and `/new_turtle`
   (→ appended to `turtle_list`), then starts the tick timer.

**Custom looping executor.** BTEng ships **no Repeat/loop decorator**, and
`RosBTExecutor._tick` cancels its timer when the tree returns a terminal
(non-RUNNING) status. The C++ `Repeat num_cycles="-1"` is therefore reproduced
by overriding `_tick()`: when the hunt tree completes one cycle the controller
calls `reset_tree()` (every node → IDLE) and keeps ticking, so the hunter loops
forever. The XML root is just the single hunt `Sequence` — there is no
Repeat/ForceSuccess wrapper in the XML.

**Node registration & resolution.** Custom nodes are registered with BTEng's
global factory via the `@register_node()` decorator (in `turtle_bt_nodes.py`).
The controller imports that module so the decorators run before parsing. In the
XML, nodes are addressed by **tag name == class name** (e.g. `<SelectNextTurtle/>`);
no `ID=` attribute is needed on the instance tags.

**Data flow:**
```
turtle_spawner  ──/new_turtle (TurtleTarget)──►  turtle_controller
turtlesim       ──/turtle1/pose──────────────►  turtle_controller
turtle_controller ──/turtle1/cmd_vel──────────►  turtlesim
turtle_controller ──/kill (srv)───────────────►  turtlesim
```

**Blackboard keys** (shared tree blackboard; not ROS params):

| Key | Type | Written by |
|-----|------|-----------|
| `turtle_list` | `list[TurtleTarget]` (dataclass) | `/new_turtle` callback + `CatchTurtle` |
| `main_x` / `main_y` / `main_theta` | `float` | `/turtle1/pose` callback |
| `target_name` | `str` | `SelectNextTurtle` (output port) |
| `target_x` / `target_y` | `float` | `SelectNextTurtle` (output ports) |

**BT node roster** (all in `turtle_bt_nodes.py`):

| Node | Base type | Description |
|------|-----------|-------------|
| `HasTargetTurtles` | `ConditionNode` | SUCCESS when prey list non-empty |
| `IsTurtleCaught` | `ConditionNode` | SUCCESS when within `catch_distance` (kept for parity; not in default trees) |
| `SelectNextTurtle` | `ActionNode` | picks target; `strategy` input = "sequential"/"closest"; writes `target_*` outputs |
| `MoveTurtleToTarget` | `RosStatefulActionNode` | proportional controller publishing on `/turtle1/cmd_vel` |
| `CatchTurtle` | `RosStatefulActionNode` | calls `/kill` service (fire-and-poll), removes from prey list |
| `WaitForTurtle` | `RosStatefulActionNode` | idles for `timeout_sec` then FAILURE (polite busy-wait, ROS clock) |

**Tree pattern** (per cycle, defined in each strategy XML; the loop is in the
controller, not the XML):
```
Sequence "HuntOneTurtle"
  Fallback "WaitForPrey"
    HasTargetTurtles      ← SUCCESS if any prey exists
    WaitForTurtle(1 s)    ← RUNNING for 1 s then FAILURE when canvas empty
  SelectNextTurtle        ← strategy hard-coded in the XML; writes target_*
  MoveTurtleToTarget
  CatchTurtle
```

### BTEng gotchas (do not deviate)

- **Static XML attributes arrive as strings** (`catch_distance="0.5"` → `"0.5"`).
  Node code must cast: `float(self.get_input("catch_distance", 0.5))`.
- **Validation** runs inside `set_tree()`. Every port referenced in the XML
  (`{key}` mapping or static value) must be declared in the node's
  `provided_ports()`, and any input whose `default is None` is treated as
  **required** and must be mapped or given a static value. Give every input a
  non-None default.
- **`<TreeNodesModel>` directions must match `provided_ports()`.** The model maps
  each node's port name → direction; the parser uses it to route `attr="{key}"`
  references to `input_ports` vs `output_ports`. If a direction disagrees with
  the node's `provided_ports()`, validation **fails** at startup. e.g.
  `SelectNextTurtle.target_*` are `output_port`; `MoveTurtleToTarget.target_*`
  are `input_port`.
- **ros_node is injected at `set_tree()` time** (deferred). Nodes are constructed
  as `cls(name=name, config=config)` with no ros_node — never touch ROS at
  construction. Use `self._require_ros_node()` / mixin helpers at runtime only.
- **Subclassing `RosBTExecutor` without calling its `__init__`** (what
  `turtle_controller_node.py` does — the tree needs parameters read after node
  init) means none of the state its methods rely on exists. `set_tree()` reads
  `self._ros_node` on its first line, and `halt()`/`run()` read `_final_status`
  / `_halted` / `_spinning`. Set all of them right after `Node.__init__`;
  `_ros_node = None` is what makes `set_tree()` inject `self`. Symptom when
  missing: `AttributeError: object has no attribute '_ros_node'` at startup —
  the controller dies while turtlesim and the spawner keep running, so the
  canvas fills with prey and the hunter never moves.
- **Create publishers/clients in `setup()` (called once), not in `on_start()`.**
  The looping executor re-activates nodes every cycle and `create_publisher` is
  not idempotent. `_init_service_client` IS idempotent (guarded), so it may be
  called from `on_start`/`setup`.

### Adding a new BT node to bt_turtlesim_ctrl

1. Add the class in `bt_turtlesim_ctrl/turtle_bt_nodes.py`, subclassing the
   appropriate BTEng base (`ConditionNode`, `ActionNode`,
   `RosStatefulActionNode`, …) and decorate it with `@register_node()`.
2. Declare its ports in `provided_ports()` — every port used in XML, each with a
   non-None default (None = required).
3. Reference it in the XML by tag name (`<MyNode .../>`).
4. Add a matching `<MyNode>` entry under `<TreeNodesModel>` in **both** strategy
   XMLs, with `<input_port>` / `<output_port>` directions that match
   `provided_ports()` exactly — otherwise tree validation fails at startup.

### Configuration

**`bt_turtlesim_ctrl/config/params.yaml`** and launch arguments:

- `turtle_spawner` — `initial_spawn_count` (default 3), `min_interval` /
  `max_interval` spawn timing (default 2.0 / 4.0 s).
- `turtle_controller` — `tree_xml_file` (absolute path to the chosen strategy XML
  in the install share, supplied by the launch file), `strategy`
  (`sequential`/`closest`), `tick_interval` (default 0.02 → ~50 Hz),
  `zmq_port` (default 2667), `enable_zmq` (default True).

## Docker details

- **Network/IPC:** host mode required for ROS 2 DDS discovery; it also exposes
  the BTEng ZmqPublisher (`tcp://*:2667`) directly on the host (no port mapping).
- **ROS_DOMAIN_ID=42** — set in `docker-compose.yaml` to avoid collisions with
  other ROS 2 processes.
- **X11 is required** for the turtlesim GUI window (run `xhost +local:docker` on
  the host first). BT *introspection*, however, needs no GUI — it is the BTEng
  ZmqPublisher (port 2667) + colored console logger, not a GUI tool like Groot2.
- **Build cache:** the host `./.colcon/{build,install,log}` directories are
  bind-mounted into `/dev_ws/` so colcon artifacts persist across container restarts.

## Key file locations

| Path | Purpose |
|------|---------|
| `interfaces/msg/TurtleTarget.msg` | Custom message: prey turtle name + position |
| `interfaces/CMakeLists.txt` | Builds bt_turtlesim_interfaces (must build before ctrl) |
| `bt_turtlesim_ctrl/bt_turtlesim_ctrl/turtle_bt_nodes.py` | All BTEng BT node classes (registered via `@register_node()`) |
| `bt_turtlesim_ctrl/bt_turtlesim_ctrl/turtle_controller_node.py` | Custom looping BT executor + ROS subscriptions (`main`) |
| `bt_turtlesim_ctrl/bt_turtlesim_ctrl/turtle_spawner_node.py` | Periodic prey spawner (`main`) |
| `bt_turtlesim_ctrl/bt_structures/turtle_hunter_sequential.xml` | Sequential strategy tree (BTEng XML) |
| `bt_turtlesim_ctrl/bt_structures/turtle_hunter_closest.xml` | Closest-first strategy tree (BTEng XML) |
| `bt_turtlesim_ctrl/bt_structures/turtlesim.btproj` | BTEng project file (convenience) |
| `bt_turtlesim_ctrl/config/params.yaml` | Spawner + controller parameters |
| `bt_turtlesim_ctrl/launch/turtlesim_bt.launch.py` | Turtlesim demo launch file |
| `bt_turtlesim_ctrl/setup.py` | ament_python packaging + console_scripts entry points |
| `docker/Dockerfile` | Image; pip-installs `bteng`, `bteng-ros2`, apt-installs turtlesim |
| `dependencies.repos` | Documents that bteng/bteng-ros2 come from pip (no vcstool sources) |
| `run.sh` | Optional one-command wrapper (checks → build → launch); see "Running" |
| `tools/requirements.txt` | Host-side deps for the ZMQ viewers (pyzmq, rich), installed into `.venv` |
