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

---

## 3. Launch arguments

| Argument | Default | Meaning |
|----------|---------|---------|
| `strategy` | `sequential` | Hunting strategy: `sequential` (FIFO) or `closest` (nearest-first). Also picks which XML tree is loaded. |
| `min_interval` | *(empty → 2.0)* | Lower bound (s) between periodic prey spawns. |
| `max_interval` | *(empty → 4.0)* | Upper bound (s) between periodic prey spawns. |
| `initial_spawn_count` | *(empty → 3)* | Prey spawned in the startup burst (`0` disables the burst). |
| `enable_zmq` | `true` | Enable the BTEng `ZmqPublisher` live stream on port 1667. |

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
| `zmq_port` | `1667` | TCP port for the `ZmqPublisher` stream. |
| `enable_zmq` | `true` | Start the ZMQ publisher (needs `pyzmq`). |

---

## 5. Watching the behavior tree live (ZMQ stream)

There is **no Groot2** here — Groot2 speaks BehaviorTree.CPP's wire protocol,
which is incompatible with BTEng's event stream. Instead BTEng streams its own
JSON tick events over a ZMQ `PUB` socket (topic `bteng`). With host networking,
the port is reachable straight from the host.

A ready-to-run subscriber ships in the repo at `tools/bt_zmq_viewer.py`
(needs `pip install pyzmq` on the host). With the demo running, just:

```bash
python3 tools/bt_zmq_viewer.py            # formatted tick log
python3 tools/bt_zmq_viewer.py --raw      # raw JSON events
python3 tools/bt_zmq_viewer.py --host localhost --port 1667
```

Its core is the same handful of lines, if you'd rather inline it:

```python
import json
import zmq

ctx = zmq.Context.instance()
sock = ctx.socket(zmq.SUB)
sock.connect("tcp://localhost:1667")
sock.setsockopt(zmq.SUBSCRIBE, b"bteng")   # topic prefix

print("Listening for BTEng tick events on tcp://localhost:1667 …")
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
| Colcon picks up a stale build | `rm -rf build install log` (or `.colcon/*` on the host) and rebuild. |

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
