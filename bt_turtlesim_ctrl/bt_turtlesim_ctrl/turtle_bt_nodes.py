# ============================================================================
# TURTLESIM BT NODES  (BTEng + bteng-ros2)
# ============================================================================
# BTEng behavior-tree nodes that drive turtle1 to hunt prey turtles.
# Ported from the BehaviorTree.CPP version (turtlesim_btcpp).
#
# Each node is registered with the global NodeFactory via @register_node() so
# the XML parser can instantiate it by tag name (tag == class name).
#
# Condition nodes:
#   HasTargetTurtles   — SUCCESS when the prey list is non-empty
#   IsTurtleCaught     — SUCCESS when turtle1 is within catch_distance of target
#
# Action nodes:
#   SelectNextTurtle   — picks a target using a strategy
#                        "sequential" : first-in-first-out (FIFO)
#                        "closest"    : nearest Euclidean distance
#   MoveTurtleToTarget — drives turtle1 toward a target (proportional control)
#   CatchTurtle        — calls /kill, removes the turtle from the prey list
#   WaitForTurtle      — idles for timeout_sec, then FAILURE (polite busy-wait)
#
# Blackboard keys (shared on the tree blackboard):
#   "turtle_list"            list[TurtleTarget]   maintained by controller + CatchTurtle
#   "main_x/main_y/main_theta" float              updated by /turtle1/pose subscription
#   "target_name"            str                  written by SelectNextTurtle (output port)
#   "target_x"/"target_y"    float                written by SelectNextTurtle (output port)
#
# Important BTEng notes:
#   * Static XML attributes arrive as strings -> always cast (float(...)).
#   * Publishers/clients are created in setup() (called once), never repeatedly
#     in on_start() — the looping executor re-activates nodes every hunt cycle.
#   * ros_node is injected by the executor at set_tree() time; use mixin helpers
#     (self.create_publisher, self.ros_logger, self._require_ros_node) at runtime.
# ============================================================================
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from bteng import (
    ActionNode,
    ConditionNode,
    NodeStatus,
    InputPort,
    OutputPort,
    PortDefinition,
    register_node,
)
from bteng_ros2 import (
    RosTopicMixin,
    RosStatefulActionNode,
)

from geometry_msgs.msg import Twist
from turtlesim.srv import Kill


# ---------------------------------------------------------------------------
# Shared data type stored on the blackboard
# ---------------------------------------------------------------------------
@dataclass
class TurtleTarget:
    """A single prey turtle: ROS name + canvas position."""
    name: str
    x: float = 0.0
    y: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _wrap_angle(a: float) -> float:
    """Wrap an angle to [-pi, pi]."""
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def _get_turtle_list(bb) -> List[TurtleTarget]:
    return list(bb.get("turtle_list", []) or [])


def _get_main_pose(bb):
    return (
        float(bb.get("main_x", 0.0) or 0.0),
        float(bb.get("main_y", 0.0) or 0.0),
        float(bb.get("main_theta", 0.0) or 0.0),
    )


# ===========================================================================
# CONDITION NODES
# ===========================================================================
@register_node()
class HasTargetTurtles(RosTopicMixin, ConditionNode):
    """SUCCESS when the prey list has at least one entry."""

    @classmethod
    def provided_ports(cls) -> List[PortDefinition]:
        return []

    def tick(self) -> NodeStatus:
        prey = _get_turtle_list(self.blackboard)
        return NodeStatus.SUCCESS if prey else NodeStatus.FAILURE


@register_node()
class IsTurtleCaught(RosTopicMixin, ConditionNode):
    """SUCCESS when turtle1 is within catch_distance of the current target.

    (Kept for parity with the C++ roster; not used by the default trees.)
    """

    @classmethod
    def provided_ports(cls) -> List[PortDefinition]:
        return [
            InputPort("catch_distance", "Catch radius (m)", default=0.5),
            InputPort("target_x", "Target X coordinate", default=0.0),
            InputPort("target_y", "Target Y coordinate", default=0.0),
        ]

    def tick(self) -> NodeStatus:
        tx = float(self.get_input("target_x", 0.0))
        ty = float(self.get_input("target_y", 0.0))
        catch = float(self.get_input("catch_distance", 0.5))
        mx, my, _ = _get_main_pose(self.blackboard)
        return (
            NodeStatus.SUCCESS
            if math.hypot(tx - mx, ty - my) < catch
            else NodeStatus.FAILURE
        )


# ===========================================================================
# ACTION NODES
# ===========================================================================
@register_node()
class SelectNextTurtle(RosTopicMixin, ActionNode):
    """Select the next target turtle from the prey list.

    strategy="sequential" -> oldest entry (FIFO)
    strategy="closest"    -> nearest turtle to turtle1
    Writes target_name / target_x / target_y to the blackboard (output ports).
    """

    @classmethod
    def provided_ports(cls) -> List[PortDefinition]:
        return [
            InputPort("strategy", "'sequential' (FIFO) or 'closest' (nearest)",
                      default="sequential"),
            OutputPort("target_name", "Name of the selected prey turtle"),
            OutputPort("target_x", "X position of the selected prey"),
            OutputPort("target_y", "Y position of the selected prey"),
        ]

    def tick(self) -> NodeStatus:
        prey = _get_turtle_list(self.blackboard)
        if not prey:
            return NodeStatus.FAILURE

        strategy = str(self.get_input("strategy", "sequential"))
        log = self.ros_logger()

        if strategy == "closest":
            mx, my, _ = _get_main_pose(self.blackboard)
            selected = min(prey, key=lambda t: math.hypot(t.x - mx, t.y - my))
            dist = math.hypot(selected.x - mx, selected.y - my)
            log.info(
                f"🎯  [SelectNextTurtle] closest  → '{selected.name:<10}'  "
                f"dist={dist:.2f} m  |  queue: {len(prey)}"
            )
        else:
            selected = prey[0]
            log.info(
                f"🎯  [SelectNextTurtle] sequential → '{selected.name:<10}'  "
                f"|  queue: {len(prey)}"
            )

        self.set_output("target_name", selected.name)
        self.set_output("target_x", float(selected.x))
        self.set_output("target_y", float(selected.y))
        return NodeStatus.SUCCESS


@register_node()
class MoveTurtleToTarget(RosStatefulActionNode):
    """Drive turtle1 toward (target_x, target_y) with proportional control.

    RUNNING while moving, SUCCESS when within catch_distance. Publishes
    geometry_msgs/Twist on /turtle1/cmd_vel every tick.
    """

    @classmethod
    def provided_ports(cls) -> List[PortDefinition]:
        return [
            InputPort("target_x", "Target X position", default=0.0),
            InputPort("target_y", "Target Y position", default=0.0),
            InputPort("target_name", "Target name (for logging)", default="?"),
            InputPort("catch_distance", "Catch radius (m)", default=0.5),
            InputPort("linear_gain", "Linear P gain", default=1.5),
            InputPort("angular_gain", "Angular P gain", default=4.0),
            InputPort("max_linear_speed", "Max forward speed (m/s)", default=2.0),
            InputPort("max_angular_speed", "Max turn rate (rad/s)", default=3.0),
            InputPort("heading_tolerance", "Turn-in-place threshold (rad)", default=0.4),
        ]

    def setup(self) -> None:
        # Created once; survives across hunt cycles (executor never re-runs setup).
        self._cmd_pub = self.create_publisher(Twist, "/turtle1/cmd_vel", 10)

    def on_start(self) -> NodeStatus:
        tname = str(self.get_input("target_name", "?"))
        self.ros_logger().info(f"🏃  [MoveTurtleToTarget] Chasing '{tname:<10}'…")
        return self._step()

    def on_running(self) -> NodeStatus:
        return self._step()

    def on_halted(self) -> None:
        self._cmd_pub.publish(Twist())
        self.ros_logger().warn("⛔  [MoveTurtleToTarget] halted — turtle stopped")

    def _step(self) -> NodeStatus:
        tx = float(self.get_input("target_x", 0.0))
        ty = float(self.get_input("target_y", 0.0))
        catch = float(self.get_input("catch_distance", 0.5))
        kp_lin = float(self.get_input("linear_gain", 1.5))
        kp_ang = float(self.get_input("angular_gain", 4.0))
        max_lin = float(self.get_input("max_linear_speed", 2.0))
        max_ang = float(self.get_input("max_angular_speed", 3.0))
        heading_tol = float(self.get_input("heading_tolerance", 0.4))

        mx, my, mtheta = _get_main_pose(self.blackboard)
        dx, dy = tx - mx, ty - my
        dist = math.hypot(dx, dy)

        if dist < catch:
            self._cmd_pub.publish(Twist())
            return NodeStatus.SUCCESS

        angle_error = _wrap_angle(math.atan2(dy, dx) - mtheta)
        cmd = Twist()
        if abs(angle_error) > heading_tol:
            cmd.linear.x = 0.0  # turn in place until roughly aligned
        else:
            cmd.linear.x = min(kp_lin * dist, max_lin)
        cmd.angular.z = max(-max_ang, min(max_ang, kp_ang * angle_error))
        self._cmd_pub.publish(cmd)
        return NodeStatus.RUNNING


@register_node()
class CatchTurtle(RosStatefulActionNode):
    """Call the turtlesim /kill service and remove the turtle from the prey list.

    Fire-and-poll: the request is sent in on_start() and polled non-blockingly
    in on_running(), so the tree keeps ticking while the call is in flight.
    Always returns SUCCESS once acknowledged / timed out / unavailable, so the
    hunter never gets stuck on one turtle.
    """

    KILL_TIMEOUT_SEC = 2.0

    @classmethod
    def provided_ports(cls) -> List[PortDefinition]:
        return [
            InputPort("target_name", "Name of the turtle to eliminate", default=""),
        ]

    def setup(self) -> None:
        # Idempotent init creates the /kill client once.
        self._init_service_client(Kill, "/kill", call_timeout=self.KILL_TIMEOUT_SEC)

    def on_start(self) -> NodeStatus:
        self._target = str(self.get_input("target_name", ""))
        log = self.ros_logger()
        log.info(f"🪤  [CatchTurtle] Eliminating '{self._target:<10}'…")

        if not self.service_is_ready():
            log.warn(
                f"⚠️   /kill service not available — dropping '{self._target}' from list"
            )
            self._remove_from_list(self._target)
            return NodeStatus.SUCCESS

        req = Kill.Request()
        req.name = self._target
        self.call_service(req)
        return NodeStatus.RUNNING

    def on_running(self) -> NodeStatus:
        status = self.service_status()
        if status == NodeStatus.RUNNING:
            return NodeStatus.RUNNING

        log = self.ros_logger()
        if status == NodeStatus.SUCCESS:
            log.info(f"💀  '{self._target:<10}' eliminated!")
        else:
            log.warn(
                f"⚠️   Kill failed/timed out for '{self._target}' — dropping from list"
            )
        self._remove_from_list(self._target)
        return NodeStatus.SUCCESS  # always succeed so the loop advances

    def on_halted(self) -> None:
        pass

    def _remove_from_list(self, name: str) -> None:
        bb = self.blackboard
        prey = [t for t in _get_turtle_list(bb) if t.name != name]
        bb.set("turtle_list", prey, writer=self.uid)
        self.ros_logger().info(f"📋  Prey remaining: {len(prey)}")


@register_node()
class WaitForTurtle(RosStatefulActionNode):
    """Idle for timeout_sec, then return FAILURE.

    Used inside a Fallback as a polite wait when the prey list is empty.
    Timing uses the ROS clock so /use_sim_time is respected.
    """

    @classmethod
    def provided_ports(cls) -> List[PortDefinition]:
        return [
            InputPort("timeout_sec", "Wait duration (s) before FAILURE", default=1.0),
        ]

    def _now(self) -> float:
        return self._require_ros_node().get_clock().now().nanoseconds * 1e-9

    def on_start(self) -> NodeStatus:
        self._start = self._now()
        self.ros_logger().info("😴  [WaitForTurtle] Canvas empty — waiting for prey…")
        return NodeStatus.RUNNING

    def on_running(self) -> NodeStatus:
        timeout = float(self.get_input("timeout_sec", 1.0))
        if (self._now() - self._start) >= timeout:
            return NodeStatus.FAILURE
        return NodeStatus.RUNNING

    def on_halted(self) -> None:
        pass
