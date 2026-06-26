#!/usr/bin/env python3
"""Live *visual* tree view for the BTEng ZmqPublisher tick stream.

Where ``bt_zmq_viewer.py`` prints a flat scrolling log, this draws the actual
behavior-tree structure (parsed from the strategy XML) and recolors each node
in place as tick events arrive on ``tcp://localhost:2667`` — a lightweight,
terminal-only alternative to Groot2 (which is incompatible with BTEng).

    python3 tools/bt_tree_viewer.py                 # sequential strategy
    python3 tools/bt_tree_viewer.py --strategy closest
    python3 tools/bt_tree_viewer.py --xml /path/to/tree.xml

Needs two small pure-Python deps on the host:  pip install rich pyzmq
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

try:
    import zmq
except ImportError:
    sys.exit("pyzmq is not installed. Install it with:  pip install rich pyzmq")

try:
    from rich.console import Group
    from rich.live import Live
    from rich.text import Text
    from rich.tree import Tree as RichTree
except ImportError:
    sys.exit("rich is not installed. Install it with:  pip install rich pyzmq")

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 2667
TOPIC = b"bteng"

# Repo layout: this file lives in <repo>/tools/, the strategy XMLs in
# <repo>/bt_turtlesim_ctrl/bt_structures/turtle_hunter_<strategy>.xml
REPO_ROOT = Path(__file__).resolve().parent.parent
BT_STRUCTURES = REPO_ROOT / "bt_turtlesim_ctrl" / "bt_structures"

# Tags that are tree wiring, not tickable nodes, plus the model section.
_SKIP_TAGS = {"TreeNodesModel"}

# status -> (rich style, glyph)
STATUS_STYLE = {
    "SUCCESS": ("green", "●"),
    "FAILURE": ("red", "●"),
    "RUNNING": ("yellow", "●"),
    "SKIPPED": ("cyan", "◌"),
    "IDLE": ("grey50", "○"),
}
IDLE_THRESHOLD = 2.0  # seconds without events -> header shows "idle"


class Node:
    """One tickable BT node: static identity from XML + live state from ZMQ."""

    __slots__ = ("tag", "name", "children", "status", "dur_ms", "ticks", "last_ts")

    def __init__(self, tag: str, name: str) -> None:
        self.tag = tag
        self.name = name or tag
        self.children: list[Node] = []
        self.status = "IDLE"
        self.dur_ms = 0.0
        self.ticks = 0
        self.last_ts = 0.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live visual view of the BTEng behavior tree.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="ZmqPublisher host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="ZmqPublisher port.")
    parser.add_argument(
        "--strategy",
        choices=("sequential", "closest"),
        default="sequential",
        help="Which strategy XML to draw the skeleton from.",
    )
    parser.add_argument(
        "--xml",
        type=Path,
        default=None,
        help="Explicit path to a strategy XML (overrides --strategy).",
    )
    return parser.parse_args(argv)


def _build_node(elem: ET.Element) -> Node | None:
    """Recursively convert an XML element into a Node, skipping wiring tags."""
    if elem.tag in _SKIP_TAGS:
        return None
    node = Node(elem.tag, elem.attrib.get("name", ""))
    for child in elem:
        sub = _build_node(child)
        if sub is not None:
            node.children.append(sub)
    return node


def load_skeleton(xml_path: Path) -> Node:
    """Parse the BTEng XML and return the root of the tickable tree."""
    root_elem = ET.parse(xml_path).getroot()
    # Find the <Tree> the controller executes (main_tree_to_execute), else first.
    main_id = root_elem.attrib.get("main_tree_to_execute")
    tree_elem = None
    for tree in root_elem.findall("Tree"):
        if main_id is None or tree.attrib.get("ID") == main_id:
            tree_elem = tree
            break
    if tree_elem is None:
        tree_elem = root_elem.find("Tree") or root_elem
    # The tickable root is the Tree's single child (e.g. the hunt Sequence).
    children = [c for c in tree_elem if c.tag not in _SKIP_TAGS]
    if len(children) == 1:
        return _build_node(children[0])
    # Defensive: wrap multiple/zero children under a synthetic root.
    root = Node("Tree", tree_elem.attrib.get("ID", "root"))
    for c in children:
        sub = _build_node(c)
        if sub is not None:
            root.children.append(sub)
    return root


def build_lookup(node: Node, lookup: dict[str, Node]) -> dict[str, Node]:
    """Index nodes by instance name and by tag (instance name wins on clash)."""
    lookup.setdefault(node.tag, node)  # class/tag key, first occurrence wins
    lookup[node.name] = node  # instance name is authoritative
    for child in node.children:
        build_lookup(child, lookup)
    return lookup


def render_tree(node: Node, rich_node: RichTree | None = None) -> RichTree:
    style, glyph = STATUS_STYLE.get(node.status, ("white", "•"))
    label = Text()
    label.append(f"{glyph} ", style=style)
    # Always show the class/tag (bold); add the instance name when it differs,
    # so e.g. "HasTargetTurtles AnyPreyAlive" maps back to the node roster.
    label.append(node.tag, style="bold")
    if node.name != node.tag:
        label.append(f" {node.name}", style="italic grey70")
    if node.status != "IDLE":
        label.append(f"  {node.status}", style=style)
        if node.dur_ms:
            label.append(f"  {node.dur_ms:>6.2f} ms", style="grey50")
        if node.ticks:
            label.append(f"  ×{node.ticks}", style="grey37")

    branch = RichTree(label, guide_style="grey37") if rich_node is None else rich_node.add(label)
    for child in node.children:
        render_tree(child, branch)
    return branch


def make_header(strategy: str, endpoint: str, total: int, rate: float, last_ts: float) -> Text:
    now = time.monotonic()
    if total == 0:
        conn = Text("○ waiting for events", style="grey50")
    elif now - last_ts > IDLE_THRESHOLD:
        conn = Text("◌ idle", style="yellow")
    else:
        conn = Text("● live", style="green")
    header = Text()
    header.append("BTEng Live Tree", style="bold white")
    header.append(f"   strategy: {strategy}", style="cyan")
    header.append(f"   {endpoint}   ", style="grey50")
    header.append_text(conn)
    header.append(f"   {rate:>4.0f} ev/s   {total} total", style="grey50")
    return header


class TreeView:
    """Holds the skeleton + live state and turns ZMQ events into colored frames."""

    def __init__(self, root: Node, strategy: str, endpoint: str) -> None:
        self.root = root
        self.strategy = strategy
        self.endpoint = endpoint
        self.lookup = build_lookup(root, {})
        self.by_uid: dict[str, Node] = {}
        self.recent: deque[float] = deque()  # event timestamps in the last second
        self.total = 0
        self.last_ts = 0.0

    def apply(self, evt: dict) -> None:
        uid = evt.get("uid")
        name = evt.get("name", "")
        node = self.by_uid.get(uid) if uid else None
        if node is None:
            # Events may carry the instance name or the class/tag — lookup covers both.
            node = self.lookup.get(name)
            if node is not None and uid:
                self.by_uid[uid] = node
        if node is None:  # unmapped node — graft it under the root so nothing is lost
            node = Node(evt.get("type", "node"), name)
            self.root.children.append(node)
            self.lookup[name] = node
            if uid:
                self.by_uid[uid] = node
        node.status = evt.get("status", node.status)
        node.dur_ms = float(evt.get("dur_ms", 0.0) or 0.0)
        node.ticks += 1
        node.last_ts = time.monotonic()
        self.total += 1
        self.last_ts = node.last_ts
        self.recent.append(node.last_ts)

    def renderable(self) -> Group:
        now = time.monotonic()
        while self.recent and now - self.recent[0] > 1.0:
            self.recent.popleft()
        header = make_header(self.strategy, self.endpoint, self.total, len(self.recent), self.last_ts)
        return Group(header, Text(), render_tree(self.root))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    xml_path = args.xml or BT_STRUCTURES / f"turtle_hunter_{args.strategy}.xml"
    if not xml_path.is_file():
        sys.exit(f"Strategy XML not found: {xml_path}")

    endpoint = f"tcp://{args.host}:{args.port}"
    view = TreeView(load_skeleton(xml_path), args.strategy, endpoint)

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.SUB)
    sock.connect(endpoint)
    sock.setsockopt(zmq.SUBSCRIBE, TOPIC)
    poller = zmq.Poller()
    poller.register(sock, zmq.POLLIN)

    with Live(view.renderable(), refresh_per_second=15, screen=False) as live:
        try:
            while True:
                if dict(poller.poll(timeout=100)).get(sock) == zmq.POLLIN:
                    _topic, _, payload = sock.recv().partition(b" ")
                    try:
                        view.apply(json.loads(payload))
                    except json.JSONDecodeError:
                        pass
                live.update(view.renderable())
        except KeyboardInterrupt:
            pass
        finally:
            sock.close(linger=0)
            ctx.term()
    print("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
