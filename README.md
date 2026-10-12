# BTEng ROS 2 Demo

<!--
  Optional banner image (TODO): drop a docs/banner.png to show the live demo here.
  <p align="center">
    <img src="docs/banner.png" alt="BTEng ROS 2 Turtlesim prey-hunter demo" width="100%">
  </p>
-->

A **BTEng** (pure-Python behavior trees) showcase running in a containerized ROS 2
Jazzy environment. A hunter turtle chases and eliminates spawned prey turtles
using an **XML-defined** behavior tree with two selectable strategies, and you can
watch the tree tick live over BTEng's own **ZmqPublisher** stream on port **2667**.

| Package | What it does | Live stream |
|---------|-------------|-------------|
| `bt_turtlesim_ctrl` | Turtlesim prey-hunting demo — a hunter turtle chases and eliminates spawned prey turtles using a BTEng tree with two selectable strategies | **ZMQ 2667** |
| `bt_turtlesim_interfaces` | Custom ROS 2 message (`TurtleTarget.msg`) shared between spawner and controller | — |

Built on:

- 🌳 **BTEng** — the behavior-tree engine: <https://pypi.org/project/bteng/> · <https://github.com/mdirzpr/BTEng_ros2>
- 🤖 **bteng-ros2** — ROS 2 base classes & executor: <https://pypi.org/project/bteng-ros2/>

📚 **Docs:** [docs/USAGE.md](docs/USAGE.md) — full run guide (Docker + native), parameter
reference, and a copy-paste ZMQ stream viewer · [CLAUDE.md](CLAUDE.md) — architecture & dev guide.

---

## 🚀 Quick Start

### 1. Build the Docker image

```bash
docker compose build
```

### 2. Start a container shell

```bash
# Interactive (recommended)
docker compose run --rm dev bash

# Or background + attach
docker compose up -d dev
docker compose exec dev bash
```

### 3. Build the ROS 2 workspace

```bash
cd /dev_ws
colcon build --symlink-install
source install/setup.bash
```

> `bt_turtlesim_interfaces` (ament_cmake) builds before `bt_turtlesim_ctrl`
> (ament_python). A plain `colcon build` orders this automatically.

### 4. Run a demo

```bash
# 🐢 Turtlesim prey-hunter (sequential strategy — FIFO)
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py

# 🐢 Turtlesim prey-hunter (closest-first strategy — greedy nearest)
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py strategy:=closest
```

Watch the colored tick log in the console, and (optionally) connect a ZMQ
client to `tcp://localhost:2667` for the live event stream (see below).

---

## 😴 Lazy Start (optional `./run.sh`)

The four steps above are the real workflow and stay fully supported. If you'd
rather not type them, `./run.sh` chains exactly those same commands — checking
the Docker image, the colcon workspace and the host `.venv`, building only
what's missing, then launching:

```bash
./run.sh                  # doctor → image → workspace → launch (sequential)
./run.sh closest          # same, closest-first strategy
```

| Command | What it does |
|---------|--------------|
| `./run.sh` / `./run.sh demo` | Build whatever is missing, then `ros2 launch …` (default: `sequential`) |
| `./run.sh closest` | Shorthand for `demo strategy:=closest` |
| `./run.sh demo min_interval:=1.0 enable_zmq:=false` | Any other argument goes straight to `ros2 launch` |
| `./run.sh setup` | Prepare everything up front: `.venv`, image, workspace |
| `./run.sh build` | Build the image if missing + force a `colcon build` |
| `./run.sh rebuild` | Rebuild the image from scratch too (after `Dockerfile` / `entrypoint.sh` edits) |
| `./run.sh shell` | Interactive dev shell in the container (= `docker compose run --rm dev bash`) |
| `./run.sh tree [closest]` | Live **visual** BT viewer on the host (auto-creates `.venv`) |
| `./run.sh viewer` | Flat live tick log on the host |
| `./run.sh doctor` | Check docker, X11, image, workspace, `.venv` — changes nothing |
| `./run.sh stop` / `./run.sh clean` | `docker compose down` / wipe `.colcon/*` build artifacts |

It also runs `xhost +local:docker` for you when the X11 grant is missing, and
creates `.venv` from [`tools/requirements.txt`](tools/requirements.txt) the
first time you ask for a viewer.

Not sure what it will do? Nothing is hidden — `--dry-run` prints the underlying
commands instead of running them:

```bash
./run.sh --dry-run closest
# $ env UID=1000 GID=1000 docker compose run --rm dev bash -c "ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py strategy:=closest"
```

Typical two-terminal session:

```bash
./run.sh closest      # terminal 1 — the demo
./run.sh tree closest # terminal 2 — the live tree view
```

---

## 🐢 Turtlesim Prey-Hunting Demo

### How it works

1. **`turtle_spawner`** creates a new prey turtle at a random position on the
   canvas every 2–4 seconds (configurable) and publishes it on `/new_turtle`.
2. **`turtle_controller`** runs a BTEng behavior tree, loaded from XML, that
   drives `turtle1` to catch and eliminate each prey.
3. Two hunting strategies are available — selected at launch time:

| Strategy | Behavior |
|----------|----------|
| `sequential` | Catch turtles in the order they appeared (FIFO) |
| `closest` | Always chase the nearest turtle first (greedy) |

### The tree (defined in XML)

The strategy XML in `bt_turtlesim_ctrl/bt_structures/` defines a single hunt
cycle — there is **no** infinite-loop wrapper in the XML:

```
Sequence "HuntOneTurtle"
  Fallback "WaitForPrey"
    HasTargetTurtles      ← SUCCESS if any prey exists
    WaitForTurtle(1 s)    ← polite idle, then FAILURE when the canvas is empty
  SelectNextTurtle        ← strategy hard-coded in the XML; writes target_*
  MoveTurtleToTarget      ← proportional controller on /turtle1/cmd_vel
  CatchTurtle             ← calls /kill, removes prey from the list
```

The "loop forever" behavior of the original C++ `Repeat num_cycles="-1"` is
reproduced by a **custom looping executor** in the controller (BTEng ships no
Repeat decorator), which `reset_tree()`s and re-ticks after each completed
cycle. See [CLAUDE.md](CLAUDE.md) for the full architecture.

### Launch options

```bash
# Default (sequential strategy, ZMQ stream enabled on 2667)
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py

# Closest-first strategy
ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py strategy:=closest
```

---

## 🛰️ Live Introspection (BTEng ZmqPublisher, port 2667)

This demo does **not** use Groot2. Groot2 speaks BehaviorTree.CPP's wire
protocol, which is **incompatible** with BTEng's event stream — they cannot
interoperate. Instead, introspection is provided by BTEng itself:

- a colored **console Logger** sink (always on — just watch the controller log), and
- an optional **`ZmqPublisher`** that streams tick events on `tcp://*:2667`.

The ZMQ stream is an optional dependency. To enable it:

```bash
pip install 'bteng[zmq]'   # pulls in pyzmq
```

Then point any ZMQ subscriber at `tcp://localhost:2667` to receive the live
tick/status events. If `pyzmq` is missing the controller logs a warning and
continues with the console logger only. The port and enable flag are launch /
node parameters (`zmq_port`, `enable_zmq`).

---

## 🐳 Docker Reference

| Command | Description |
|---------|-------------|
| `docker compose build` | Build the image |
| `docker compose run --rm dev bash` | Start interactive container |
| `docker compose up -d dev` | Start in background |
| `docker compose exec dev bash` | Attach to running container |
| `docker compose down` | Stop and remove containers |
| `docker compose logs -f dev` | View logs |

Each of these has a `./run.sh` shortcut (`build`, `shell`, `stop`, …) — see
[Lazy Start](#-lazy-start-optional-runsh). The wrapper is a convenience layer
only; the commands in this table remain the reference workflow.

To open a second terminal in a running container:
```bash
docker compose exec dev bash
source /dev_ws/install/setup.bash
```

---

## ⚠️ Troubleshooting

**No ZMQ stream** — install the optional extra: `pip install 'bteng[zmq]'`. The
demo still runs (console logger only) without it.

**ROS 2 domain isolation** — the container uses `ROS_DOMAIN_ID=42` to avoid
conflicts with other ROS 2 nodes on the network.

**Tree validation error on startup** — every port referenced in the XML
(`{key}` mapping or static value) must be declared in the node's
`provided_ports()`, and the `<TreeNodesModel>` port directions must match. See
CLAUDE.md → "Adding a new BT node".

**Build order** — `bt_turtlesim_interfaces` must be built before
`bt_turtlesim_ctrl`. A plain `colcon build` handles this automatically.

---

## 🔗 Related

For the **BehaviorTree.CPP** version of this demo, check this repository:
https://github.com/mdirzpr/turtlesim_btcpp

---

## 📝 License

MIT — see [LICENSE](LICENSE) for details.
