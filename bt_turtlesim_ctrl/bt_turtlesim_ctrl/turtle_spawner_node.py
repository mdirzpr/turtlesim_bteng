# ============================================================================
# TURTLE SPAWNER NODE
# ============================================================================
# Periodically spawns prey turtles into turtlesim and announces each one on
# /new_turtle so the BTEng hunter controller can chase it.
#
# Behaviour (mirrors the original C++ spawner):
#   * Fire an initial staggered burst of `initial_spawn_count` turtles, the
#     first ~0.5 s after start-up and each subsequent one ~0.4 s later, using
#     one-shot timers so the /spawn service calls don't collide.
#   * Once the burst is complete, switch to periodic mode: re-arm a timer with a
#     fresh random interval in [min_interval, max_interval] after every spawn.
#   * Each turtle is named "prey_N", placed at a random (x, y) in [1, 10] with a
#     random heading in [0, 2*pi]. On a successful /spawn response the turtle is
#     published as a TurtleTarget on /new_turtle.
#
# /spawn calls are non-blocking: call_async with a done-callback that
# publishes the TurtleTarget once turtlesim confirms the spawn.
# ============================================================================
from __future__ import annotations

import math
import random

import rclpy
from rclpy.node import Node

from turtlesim.srv import Spawn
from bt_turtlesim_interfaces.msg import TurtleTarget


class TurtleSpawnerNode(Node):
    """rclpy node that spawns prey turtles and announces them on /new_turtle."""

    def __init__(self) -> None:
        super().__init__("turtle_spawner")

        self.declare_parameter("min_interval", 2.0)
        self.declare_parameter("max_interval", 4.0)
        self.declare_parameter("initial_spawn_count", 3)

        min_s = float(self.get_parameter("min_interval").value)
        max_s = float(self.get_parameter("max_interval").value)
        initial = int(self.get_parameter("initial_spawn_count").value)

        self._turtle_count = 0
        self._rng = random.Random()

        self._spawn_client = self.create_client(Spawn, "/spawn")
        self._new_turtle_pub = self.create_publisher(TurtleTarget, "/new_turtle", 10)

        # Staggered one-shot timers for the initial burst, and the recurring
        # periodic timer (kept as handles so we can cancel/destroy them).
        self._burst_timers: list = []
        self._periodic_timer = None

        log = self.get_logger()
        log.info("╔══════════════════════════════════════════════════╗")
        log.info("║        🥚  Turtle Spawner  🐢                    ║")
        log.info("╠══════════════════════════════════════════════════╣")
        log.info(f"║  Initial burst : {initial:<3} turtles                     ║")
        log.info(f"║  Then every    : {min_s:.1f} – {max_s:.1f} seconds              ║")
        log.info("║  Topic         : /new_turtle                     ║")
        log.info("╚══════════════════════════════════════════════════╝")

        # Wait briefly for turtlesim to come up, then fire the initial burst.
        # Each burst turtle is staggered by 0.4 s to avoid service-call collisions.
        for i in range(initial):
            delay = 0.5 + i * 0.4
            timer = self.create_timer(delay, lambda: self._on_burst_timer())
            self._burst_timers.append(timer)

        # If no initial burst requested, go straight to periodic mode.
        if initial <= 0:
            self._schedule_next_spawn()

    # ── Initial burst ─────────────────────────────────────────────────────────
    def _on_burst_timer(self) -> None:
        # One-shot semantics: cancel & drop the front timer (the one that fired).
        if self._burst_timers:
            front = self._burst_timers.pop(0)
            front.cancel()
            self.destroy_timer(front)

        self._do_spawn()

        if not self._burst_timers:
            self.get_logger().info(
                "🐣  Initial burst complete — switching to periodic mode"
            )
            self._schedule_next_spawn()

    # ── Periodic mode ─────────────────────────────────────────────────────────
    def _schedule_next_spawn(self) -> None:
        min_s = float(self.get_parameter("min_interval").value)
        max_s = float(self.get_parameter("max_interval").value)
        interval_s = self._rng.uniform(min_s, max_s)

        self.get_logger().info(f"⏱️   Next spawn in {interval_s:.1f} s")

        self._periodic_timer = self.create_timer(
            interval_s, lambda: self._on_periodic_timer()
        )

    def _on_periodic_timer(self) -> None:
        # One-shot: cancel & destroy, spawn, then re-arm with a fresh interval.
        if self._periodic_timer is not None:
            self._periodic_timer.cancel()
            self.destroy_timer(self._periodic_timer)
            self._periodic_timer = None

        self._do_spawn()
        self._schedule_next_spawn()

    # ── Spawning ──────────────────────────────────────────────────────────────
    def _do_spawn(self) -> None:
        if not self._spawn_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn(
                "⚠️   /spawn service not available — skipping cycle"
            )
            return

        self._turtle_count += 1
        name = f"prey_{self._turtle_count}"

        x = self._rng.uniform(1.0, 10.0)
        y = self._rng.uniform(1.0, 10.0)
        theta = self._rng.uniform(0.0, 2.0 * math.pi)

        request = Spawn.Request()
        request.name = name
        request.x = float(x)
        request.y = float(y)
        request.theta = float(theta)

        self.get_logger().info(
            f"🥚  Spawning '{name:<10}' at "
            f"(x={x:.2f}, y={y:.2f}, θ={theta:.2f} rad)…"
        )

        future = self._spawn_client.call_async(request)
        future.add_done_callback(
            lambda fut, name=name, x=x, y=y: self._on_spawn_response(fut, name, x, y)
        )

    def _on_spawn_response(self, future, name: str, x: float, y: float) -> None:
        try:
            response = future.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"❌  Spawn FAILED for '{name}': {exc}")
            return

        if response is None or not response.name:
            self.get_logger().error(f"❌  Spawn FAILED for '{name}'")
            return

        self.get_logger().info(
            f"✅  '{response.name}' alive at ({x:.2f}, {y:.2f}) "
            f"— total spawned: {self._turtle_count}"
        )

        msg = TurtleTarget()
        msg.name = response.name
        msg.x = float(x)
        msg.y = float(y)
        self._new_turtle_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TurtleSpawnerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
