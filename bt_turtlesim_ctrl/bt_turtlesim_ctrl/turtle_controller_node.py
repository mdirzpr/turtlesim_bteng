# ============================================================================
# TURTLE CONTROLLER NODE  (BTEng + bteng-ros2)
# ============================================================================
# Drives turtle1 to hunt prey turtles with a BTEng behavior tree loaded from XML.
#
# This is a custom looping executor. BTEng ships no Repeat/loop decorator, and
# bteng-ros2's RosBTExecutor cancels its tick timer when the tree returns a
# terminal status. The C++ `Repeat num_cycles="-1"` is reproduced here by
# overriding _tick(): when the hunt tree completes one cycle we reset_tree() and
# keep ticking, so the hunter loops forever. The XML therefore contains only the
# single hunt Sequence (no Repeat/ForceSuccess wrapper).
#
# The controller also owns the ROS subscriptions that feed the blackboard:
#   /turtle1/pose  -> main_x / main_y / main_theta
#   /new_turtle    -> appended to turtle_list
# ============================================================================
from __future__ import annotations

import rclpy
from rclpy.node import Node

from bteng import (
    Blackboard,
    ExecutorConfig,
    Inspector,
    Logger,
    NodeStatus,
    Tree,
    TreeExecutor,
    TreeMetadata,
    XMLTreeParser,
)
from bteng_ros2 import RosBTExecutor

from turtlesim.msg import Pose
from bt_turtlesim_interfaces.msg import TurtleTarget as TurtleTargetMsg

# Importing the nodes module triggers every @register_node() so the XML parser
# can resolve the custom tags. TurtleTarget is the blackboard dataclass.
from bt_turtlesim_ctrl.turtle_bt_nodes import TurtleTarget  # noqa: F401  (registers nodes)
import bt_turtlesim_ctrl.turtle_bt_nodes  # noqa: F401  (ensures decorators run)


class TurtleHuntController(RosBTExecutor):
    """rclpy node that perpetually ticks the turtle-hunting BTEng tree.

    Subclasses RosBTExecutor to reuse its ros_node injection / clock wiring, but
    builds the tree from a parameter-supplied XML file and overrides _tick() to
    loop forever instead of stopping on completion.
    """

    def __init__(self) -> None:
        # Initialise only the rclpy.Node layer; we replicate the executor wiring
        # ourselves because the tree depends on parameters read after node init.
        Node.__init__(self, "turtle_controller")

        self.declare_parameter("tree_xml_file", "")
        self.declare_parameter("strategy", "sequential")
        self.declare_parameter("tick_interval", 0.02)
        self.declare_parameter("zmq_port", 2667)
        self.declare_parameter("enable_zmq", True)

        xml_file = self.get_parameter("tree_xml_file").value
        strategy = self.get_parameter("strategy").value
        tick_interval = float(self.get_parameter("tick_interval").value)
        zmq_port = int(self.get_parameter("zmq_port").value)
        enable_zmq = bool(self.get_parameter("enable_zmq").value)

        if not xml_file:
            raise RuntimeError("Parameter 'tree_xml_file' is required")

        self._banner(strategy, xml_file, zmq_port, enable_zmq)

        # ── Blackboard (shared by the controller and every BT node) ──────────
        self._bb = Blackboard.create("turtle_hunter")
        self._bb.set("turtle_list", [])
        self._bb.set("main_x", 0.0)
        self._bb.set("main_y", 0.0)
        self._bb.set("main_theta", 0.0)

        # ── Build the tree from XML ──────────────────────────────────────────
        root = XMLTreeParser().parse_file(xml_file, blackboard=self._bb)
        tree = Tree(TreeMetadata(id="TurtleHunter"), root, self._bb)

        # ── Executor (manual ticking; we drive the loop in _tick) ────────────
        cfg = ExecutorConfig(
            tick_interval=tick_interval,
            enable_tracing=False,
        )
        self._bt = TreeExecutor(cfg)
        # RosBTExecutor.set_tree: injects ros_node=self into all nodes, wires the
        # ROS clock into Timeout/RateController, and validates the tree.
        self.set_tree(tree)

        # ── Introspection: console logger + inspector + optional ZMQ stream ──
        # NOTE: do NOT name this attribute `self._logger` — rclpy.Node stores its
        # own logger there and get_logger() returns it; clobbering it breaks all
        # subsequent self.get_logger() calls. Use a distinct name.
        self._inspector = Inspector.create()
        self._bt_logger = Logger.create()
        self._bt_logger.add_console_sink(colored=True)
        self._bt.set_inspector(self._inspector)
        self._bt.set_logger(self._bt_logger)

        self._zmq = None
        if enable_zmq:
            try:
                from bteng import ZmqPublisher
                self._zmq = ZmqPublisher(port=zmq_port).attach(self._inspector)
                self._zmq.start()
                self.get_logger().info(
                    f"🛰️   BTEng ZmqPublisher streaming tick events on tcp://*:{zmq_port}"
                )
            except ImportError:
                self.get_logger().warn(
                    "⚠️   pyzmq not installed — ZMQ stream disabled "
                    "(install with: pip install 'bteng[zmq]')"
                )

        # ── ROS subscriptions feeding the blackboard ─────────────────────────
        self._pose_sub = self.create_subscription(
            Pose, "/turtle1/pose", self._on_pose, 10
        )
        self._new_turtle_sub = self.create_subscription(
            TurtleTargetMsg, "/new_turtle", self._on_new_turtle, 10
        )

        # ── Tick timer (drives the BT). Created last so callbacks are ready. ─
        self._timer = self.create_timer(tick_interval, self._tick)
        self.get_logger().info("🟢  BT running — Ctrl+C to stop")

    # ── Looping tick: reset and keep hunting instead of stopping ─────────────
    def _tick(self) -> None:
        status = self._bt.tick_once()
        if status != NodeStatus.RUNNING:
            # One hunt cycle finished (turtle caught, or empty-canvas wait
            # expired). Reset every node to IDLE and start the next cycle.
            self._bt.reset_tree()

    # ── Subscriptions ────────────────────────────────────────────────────────
    def _on_pose(self, msg: Pose) -> None:
        self._bb.set("main_x", float(msg.x))
        self._bb.set("main_y", float(msg.y))
        self._bb.set("main_theta", float(msg.theta))

    def _on_new_turtle(self, msg: TurtleTargetMsg) -> None:
        prey = list(self._bb.get("turtle_list", []) or [])
        prey.append(TurtleTarget(name=msg.name, x=float(msg.x), y=float(msg.y)))
        self._bb.set("turtle_list", prey)
        self.get_logger().info(
            f"🐢  New prey spotted: '{msg.name:<10}' at "
            f"(x={msg.x:.2f}, y={msg.y:.2f})  |  🎯 queue: {len(prey)}"
        )

    # ── Teardown ─────────────────────────────────────────────────────────────
    def cleanup(self) -> None:
        try:
            self._timer.cancel()
        except Exception:
            pass
        self._bt.halt_tree()
        if self._zmq is not None:
            self._zmq.stop()

    def _banner(self, strategy, xml_file, zmq_port, enable_zmq) -> None:
        log = self.get_logger()
        log.info("╔══════════════════════════════════════════════════╗")
        log.info("║       🐢  Turtlesim BTEng Controller  🌳         ║")
        log.info("╠══════════════════════════════════════════════════╣")
        log.info(f"║  Strategy : {strategy:<37}║")
        log.info(f"║  ZMQ      : {'port ' + str(zmq_port) if enable_zmq else 'disabled':<37}║")
        log.info("╚══════════════════════════════════════════════════╝")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TurtleHuntController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.cleanup()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
