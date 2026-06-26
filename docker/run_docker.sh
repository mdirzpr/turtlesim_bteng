#!/bin/bash
# 🐢 Simple docker run helper for the Turtlesim BTEng image.
#
# Usage:
#   ./docker/run_docker.sh turtlesim_bteng:dev "ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py"
#   ./docker/run_docker.sh turtlesim_bteng:dev bash
#
# Notes:
#   - --net=host exposes the BTEng ZmqPublisher (tcp://*:2667) directly on the host.
#   - X11 is forwarded so turtlesim's window appears on your desktop.
#     Run `xhost +local:docker` on the HOST first.

# Define Docker volumes and environment variables
DOCKER_VOLUMES="
--volume="/tmp/.X11-unix:/tmp/.X11-unix:rw" \
--volume="${XAUTHORITY:-$HOME/.Xauthority}:/root/.Xauthority" \
"
DOCKER_ENV_VARS="
--env="DISPLAY" \
--env="QT_X11_NO_MITSHM=1" \
--env="NVIDIA_DRIVER_CAPABILITIES=all" \
--env="ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-42}" \
"
DOCKER_ARGS=${DOCKER_VOLUMES}" "${DOCKER_ENV_VARS}

# Run the command (image = $1, command = $2)
docker run -it --net=host --ipc=host --privileged ${DOCKER_ARGS} "$1" bash -c "$2"
