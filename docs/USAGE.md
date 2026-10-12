# Usage Guide

Hands-on guide to building, running, configuring, and observing the
`turtlesim_bteng` prey-hunting demo. For the *why* behind the design, see
[../CLAUDE.md](../CLAUDE.md); for the overview, see [../README.md](../README.md).

---

## 1. Run it with Docker (recommended)

The image bundles ROS 2 Jazzy, turtlesim, and the pip-installed BTEng stack
(`bteng`, `bteng-ros2`, `pyzmq`) — nothing to install on the host but Docker
and an X server.

```bash
# 0. (host, once per login) allow the container to draw the turtlesim window
xhost +local:docker

# 1. build the image (first time, or after Dockerfile changes)
docker compose build

# 2. open a dev shell inside the container
docker compose run --rm dev bash

# 3. (inside the container) build the ROS 2 workspace
cd /dev_ws
colcon build --symlink-install
source install/setup.bash

# 4. launch the demo 🐢🌳
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py
```

A turtlesim window opens, prey turtles start appearing, and `turtle1` hunts
them down. The controller prints a colored, live BT tick log to the console.

Closest-first strategy instead of FIFO:

```bash
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py strategy:=closest
```

> **Build order:** `bt_turtlesim_interfaces` (ament_cmake) must build before
> `bt_turtlesim_ctrl` (ament_python). A plain `colcon build` orders this for you.

### Shortcut: `./run.sh`

The five steps above are the reference workflow — nothing below replaces them.
`./run.sh` is a thin wrapper that runs those exact commands for you, skipping
the ones already done:

```bash
./run.sh                 # xhost → image (if missing) → colcon (if stale) → ros2 launch
./run.sh closest         # same, closest-first strategy
```

What it checks, in order:

1. **Docker** — engine installed, Compose V2 available, daemon reachable.
   Anything missing aborts with the fix to apply.
2. **X11** — if `DISPLAY` is set but local containers aren't allowed to draw, it
   runs `xhost +local:docker` for you.
3. **Image** — builds `turtlesim_bteng:dev` via `docker compose build` when it
   doesn't exist yet (`./run.sh rebuild` forces it, e.g. after editing
   `docker/Dockerfile` or `docker/entrypoint.sh`).
4. **Workspace** — runs `colcon build --symlink-install` in the container when
   `.colcon/install/setup.bash` is missing or older than a source file.
5. **Host `.venv`** — for the `tree` / `viewer` subcommands only: creates
   `.venv` and installs `tools/requirements.txt` (pyzmq + rich), reinstalling
   only when that file changes.

Then it launches. Bare `sequential` / `closest` are shorthand for
`strategy:=…`; every other argument is forwarded to `ros2 launch` verbatim, so
the whole launch-argument table in §3 works unchanged:

```bash
./run.sh demo min_interval:=1.0 max_interval:=2.0
./run.sh demo closest enable_zmq:=false
```

Other subcommands: `setup` (prepare everything up front), `build` / `rebuild`,
`shell`, `tree` / `viewer` (§5), `doctor` (check-only, changes nothing), `stop`,
`clean`, `help`. Prefix any of them with `--dry-run` to print the underlying
commands instead of executing them:

```bash
$ ./run.sh --dry-run closest
$ env UID=1000 GID=1000 docker compose run --rm dev bash -c "ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py strategy:=closest"
```

`./run.sh doctor` is the quickest way to see what state the checkout is in
before running anything:

```
✅ docker 29.7.2 + compose 5.5.0
✅ X11 access for local containers granted (DISPLAY=:0)
✅ Docker image turtlesim_bteng:dev present
⚠️  colcon workspace is stale (sources changed) — will rebuild on next run.
✅ Host .venv present (Python 3.12.3)
```

### Second terminal into the same container

```bash
docker compose up -d dev               # start in background
docker compose exec dev bash
source /dev_ws/install/setup.bash
```

---

## 2. Run it natively (no Docker)

You need ROS 2 Jazzy + turtlesim on the host, then the BTEng stack from pip:

```bash
source /opt/ros/jazzy/setup.bash
sudo apt install ros-jazzy-turtlesim
pip install 'bteng[zmq]' bteng-ros2          # engine + ROS base classes + ZMQ stream

# in a colcon workspace (e.g. ~/ws/src/ holding this repo's two packages)
cd ~/ws
colcon build --symlink-install
source install/setup.bash

ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py
```

> `./run.sh` is Docker-only — on a native install use the commands above
> directly (the host `.venv` for the viewers is still available via
> `./run.sh setup`, or `pip install -r tools/requirements.txt`).

---

## 3. Launch arguments

| Argument | Default | Meaning |
|----------|---------|---------|
| `strategy` | `sequential` | Hunting strategy: `sequential` (FIFO) or `closest` (nearest-first). Also picks which XML tree is loaded. |
| `min_interval` | *(empty → 2.0)* | Lower bound (s) between periodic prey spawns. |
| `max_interval` | *(empty → 4.0)* | Upper bound (s) between periodic prey spawns. |
| `initial_spawn_count` | *(empty → 3)* | Prey spawned in the startup burst (`0` disables the burst). |
| `enable_zmq` | `true` | Enable the BTEng `ZmqPublisher` live stream on port 2667. |

Examples:

```bash
# faster, busier canvas
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py min_interval:=1.0 max_interval:=2.0

# closest-first, no ZMQ stream (console log only)
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py strategy:=closest enable_zmq:=false
```

Empty `min_interval` / `max_interval` / `initial_spawn_count` fall back to
`config/params.yaml` — the single source of truth for defaults.

---

## 4. Node parameters reference

Set via `config/params.yaml` or overridden by the launch file.

**`turtle_spawner`**

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `initial_spawn_count` | `3` | Burst of prey at startup (staggered ~0.4 s apart). |
| `min_interval` / `max_interval` | `2.0` / `4.0` | Random periodic spawn interval bounds (s). |

**`turtle_controller`**

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `tree_xml_file` | *(set by launch)* | Absolute path to the chosen strategy XML in the install share. |
| `strategy` | `sequential` | Passed to the tree; informational at the controller level. |
| `tick_interval` | `0.02` | BT tick period in seconds (~50 Hz). |
| `zmq_port` | `2667` | TCP port for the `ZmqPublisher` stream. |
| `enable_zmq` | `true` | Start the ZMQ publisher (needs `pyzmq`). |

---

## 5. Watching the behavior tree live (ZMQ stream)

There is **no Groot2** here — Groot2 speaks BehaviorTree.CPP's wire protocol,
which is incompatible with BTEng's event stream. Instead BTEng streams its own
JSON tick events over a ZMQ `PUB` socket (topic `bteng`). With host networking,
the port is reachable straight from the host.

Two ready-to-run viewers ship in the repo. With the demo running:

**Flat tick log** — `tools/bt_zmq_viewer.py` (needs `pip install pyzmq`):

```bash
python3 tools/bt_zmq_viewer.py            # formatted tick log
python3 tools/bt_zmq_viewer.py --raw      # raw JSON events
python3 tools/bt_zmq_viewer.py --host localhost --port 2667
```

**Visual live tree** — `tools/bt_tree_viewer.py` (needs `pip install rich pyzmq`)
draws the actual tree structure (parsed from the strategy XML) and recolors each
node in place as it ticks — 🟢 SUCCESS, 🔴 FAILURE, 🟡 RUNNING, ⚪ IDLE — a
lightweight, terminal-only stand-in for Groot2:

```bash
python3 tools/bt_tree_viewer.py                  # sequential skeleton (default)
python3 tools/bt_tree_viewer.py --strategy closest
python3 tools/bt_tree_viewer.py --xml /path/to/tree.xml
```

Pass `--strategy` to match whichever tree you launched, so the drawn skeleton
lines up with the live events.

Both need `pyzmq` (and `rich`, for the tree view) on the host. If you'd rather
not manage that yourself, `./run.sh` wraps them in a project-local `.venv` it
creates on first use from `tools/requirements.txt`:

```bash
./run.sh viewer              # = python3 tools/bt_zmq_viewer.py
./run.sh viewer --raw        # extra flags are passed through
./run.sh tree                # = python3 tools/bt_tree_viewer.py
./run.sh tree closest        # 'closest' is shorthand for --strategy closest
```

Its core is the same handful of lines, if you'd rather inline it:

```python
import json
import zmq

ctx = zmq.Context.instance()
sock = ctx.socket(zmq.SUB)
sock.connect("tcp://localhost:2667")
sock.setsockopt(zmq.SUBSCRIBE, b"bteng")   # topic prefix

print("Listening for BTEng tick events on tcp://localhost:2667 …")
while True:
    raw = sock.recv()
    _topic, _, payload = raw.partition(b" ")   # "bteng <json>"
    evt = json.loads(payload)
    print(f"{evt['name']:<20} {evt['status']:<8} {evt['dur_ms']:>6.2f} ms "
          f"{evt.get('reason','')}")
```

Each message looks like:

```json
{"ts": 1234.567, "uid": "a1b2c3d4", "name": "MoveTurtleToTarget",
 "type": "action", "status": "RUNNING", "dur_ms": 0.12, "reason": ""}
```

If `pyzmq` is not installed, the controller logs a warning and runs with the
console logger only.

---

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| turtlesim window doesn't open | Run `xhost +local:docker` on the host; ensure `DISPLAY` is set and forwarded. |
| No ZMQ stream / "pyzmq not installed" warning | `pip install 'bteng[zmq]'` (the demo still runs without it). |
| `TreeValidationError` at startup | A port used in the XML isn't declared in the node's `provided_ports()`, or a `<TreeNodesModel>` direction disagrees with it. See CLAUDE.md → "Adding a new BT node". |
| Hunter never moves / no prey | Confirm `turtle_spawner` is publishing `/new_turtle` (`ros2 topic echo /new_turtle`) and turtlesim's `/spawn` service is up. |
| ROS nodes can't see each other | Check `ROS_DOMAIN_ID` matches across terminals (the container uses `42`). |
| Colcon picks up a stale build | `rm -rf build install log` (or `.colcon/*` on the host) and rebuild — `./run.sh clean` does the host-side variant. |
| Container still shows old settings (e.g. the wrong ZMQ port) | The image was built before the change. Rebuild it: `docker compose build` or `./run.sh rebuild`. |
| `./run.sh` reports something odd | Run `./run.sh doctor` (checks only, changes nothing) and `./run.sh --dry-run <cmd>` to see the exact command it would run. |

---

## 7. Where things live

| Path | Purpose |
|------|---------|
| `bt_turtlesim_ctrl/bt_turtlesim_ctrl/turtle_bt_nodes.py` | The 6 BT node classes (`@register_node()`). |
| `bt_turtlesim_ctrl/bt_turtlesim_ctrl/turtle_controller_node.py` | Custom looping BT executor + ROS subscriptions. |
| `bt_turtlesim_ctrl/bt_turtlesim_ctrl/turtle_spawner_node.py` | Periodic prey spawner. |
| `bt_turtlesim_ctrl/bt_structures/*.xml` | The two strategy trees (BTEng XML). |
| `bt_turtlesim_ctrl/config/params.yaml` | Default parameters. |
| `bt_turtlesim_ctrl/launch/turtlesim_bt.launch.py` | Launch file. |
| `run.sh` | Optional one-command wrapper around the workflow above. |
| `tools/requirements.txt` | Host-side deps for the two viewers (pyzmq, rich). |
