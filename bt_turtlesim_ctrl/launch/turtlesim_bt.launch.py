"""
turtlesim_bt.launch.py
======================
Launches the full turtlesim BTEng demo:

  1. turtlesim_node    — the simulator (turtle1 lives here)
  2. turtle_spawner    — periodically spawns prey turtles
  3. turtle_controller — BTEng executor that hunts the prey 🐢🌳

Usage
-----
  # Sequential strategy (default): catch in order of appearance
  ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py

  # Closest-first strategy: always chase the nearest prey
  ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py strategy:=closest

  # Override spawn timing (default: 2–4 s so the queue stays full)
  ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py \\
      strategy:=sequential min_interval:=1.0 max_interval:=3.0

Live visualisation 🛰️
---------------------
  There is NO Groot2 here. The controller embeds a BTEng `ZmqPublisher`
  that streams tick events on tcp://*:1667, plus a colored console Logger.
  Install the stream extra with:  pip install 'bteng[zmq]'
  Disable the stream at launch with:  enable_zmq:=false
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def launch_setup(context, *args, **kwargs):
    strategy = LaunchConfiguration("strategy").perform(context)
    enable_zmq = LaunchConfiguration("enable_zmq").perform(context)

    pkg_share = get_package_share_directory("bt_turtlesim_ctrl")
    params_file = os.path.join(pkg_share, "config", "params.yaml")

    # Map strategy → XML file (BTEng <BTEng> format, parsed by XMLTreeParser)
    xml_map = {
        "sequential": "turtle_hunter_sequential.xml",
        "closest":    "turtle_hunter_closest.xml",
    }
    xml_filename = xml_map.get(strategy, "turtle_hunter_sequential.xml")
    tree_xml_path = os.path.join(pkg_share, "bt_structures", xml_filename)

    # Normalise enable_zmq ("true"/"false" string from CLI) to a bool.
    enable_zmq_bool = str(enable_zmq).strip().lower() in ("1", "true", "yes", "on")

    # Defaults live in config/params.yaml (single source of truth). The spawn
    # arguments below override the YAML only when the user sets them explicitly
    # (their default is "" → left unset).
    spawner_overrides = {}
    for arg, cast in (("min_interval", float),
                      ("max_interval", float),
                      ("initial_spawn_count", int)):
        value = LaunchConfiguration(arg).perform(context)
        if value != "":
            spawner_overrides[arg] = cast(value)

    # -------------------------------------------------------------------------
    # 1. turtlesim simulator
    # -------------------------------------------------------------------------
    turtlesim_node = Node(
        package="turtlesim",
        executable="turtlesim_node",
        name="turtlesim",
        output="screen",
    )

    # -------------------------------------------------------------------------
    # 2. Prey spawner
    # -------------------------------------------------------------------------
    spawner_node = Node(
        package="bt_turtlesim_ctrl",
        executable="turtle_spawner",
        name="turtle_spawner",
        output="screen",
        parameters=[params_file, spawner_overrides],
    )

    # -------------------------------------------------------------------------
    # 3. BTEng controller — owns the embedded ZmqPublisher (tcp://*:1667)
    # -------------------------------------------------------------------------
    controller_node = Node(
        package="bt_turtlesim_ctrl",
        executable="turtle_controller",
        name="turtle_controller",
        output="screen",
        parameters=[params_file, {
            "tree_xml_file": tree_xml_path,
            "strategy":      strategy,
            "enable_zmq":    enable_zmq_bool,
        }],
    )

    return [
        LogInfo(msg="🐢🌳  Launching turtlesim BTEng prey-hunting demo"),
        LogInfo(msg=f"🎯  Strategy: {strategy}  →  {xml_filename}"),
        LogInfo(
            msg=(
                "🛰️   BTEng ZmqPublisher will stream tick events on "
                "tcp://*:1667 (install with: pip install 'bteng[zmq]')"
                if enable_zmq_bool
                else "🛰️   BTEng ZMQ stream disabled (enable_zmq:=false)"
            )
        ),
        turtlesim_node,
        spawner_node,
        controller_node,
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "strategy",
            default_value="sequential",
            description="Catching strategy: 'sequential' (FIFO) or 'closest' (nearest first)",
        ),
        DeclareLaunchArgument(
            "min_interval",
            default_value="",
            description="Override min seconds between spawns. Empty = use params.yaml (2.0)",
        ),
        DeclareLaunchArgument(
            "max_interval",
            default_value="",
            description="Override max seconds between spawns. Empty = use params.yaml (4.0)",
        ),
        DeclareLaunchArgument(
            "initial_spawn_count",
            default_value="",
            description="Override prey spawned at startup (0 to disable). Empty = use params.yaml (3)",
        ),
        DeclareLaunchArgument(
            "enable_zmq",
            default_value="true",
            description="Enable the BTEng ZmqPublisher live stream on port 1667 (true/false)",
        ),
        OpaqueFunction(function=launch_setup),
    ])
