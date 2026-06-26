################################################################################
# 🐢 Turtlesim BTEng ROS 2 Example - Multi-Stage Dockerfile
#
# Author: Mahdi Rezapour (mahdi.rezapour@dfki.de)
# Created: 2024
# Updated: 2026-06
#
# Description:
#   Multi-stage Docker build for the prey-hunting BehaviorTree demo using:
#   - ROS 2 Jazzy (Robot Operating System)
#   - BTEng (pure-Python behavior tree execution engine, installed via pip)
#   - bteng-ros2 (ROS 2 base classes / executor for BTEng)
#   - turtlesim (the GUI simulator we drive)
#
#   Live introspection is provided by BTEng's ZmqPublisher on tcp://*:2667 plus
#   a colored console Logger. Groot2 is NOT used (incompatible with BTEng's
#   stream), so there is no AppImage / FUSE / Qt-SVG machinery here.
#
# Stages:
#   1. base - ROS 2 + pip-installed BTEng stack + turtlesim
#   2. dev  - Development environment with non-root user + /dev_ws overlay
#
# Build Args:
#   ROS_DISTRO - ROS 2 distribution (default: jazzy)
#   USERNAME   - Development user name (default: devuser)
#   UID/GID    - User/Group ID (default: 1000)
################################################################################

ARG ROS_DISTRO=jazzy

################################################################################
# 📦 STAGE 1: BASE IMAGE
#
# Purpose:
#   - Foundation layer with ROS 2 and all external dependencies
#   - Installs the BTEng Python stack via pip (no source/colcon build)
#   - Shared by subsequent stages to maximize layer reuse
#
# Key Components:
#   - ROS 2 Jazzy base image
#   - System libraries and build tools
#   - turtlesim (apt) + BTEng / bteng-ros2 / pyzmq (pip)
################################################################################

FROM ros:jazzy AS base

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=${ROS_DISTRO}
SHELL ["/bin/bash", "-c"]

################################################################################
# 🔧 SYSTEM DEPENDENCIES
#
# Package groups:
#   - Build tools: curl, git, build-essential, cmake (for colcon overlay build)
#   - GUI libraries: libcanberra-gtk* (suppress turtlesim GTK warnings)
#   - Python: python3-pip, python3-dev (for the BTEng pip install)
#   - ZMQ: libzmq5 (transport behind pyzmq / the BTEng ZmqPublisher)
#   - ROS middleware: rmw-cyclonedds-cpp (DDS implementation)
#   - turtlesim: the simulator this demo drives
################################################################################

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git build-essential cmake \
    libcanberra-gtk-module libcanberra-gtk3-module \
    libzmq5 \
    python3-pip python3-dev iputils-ping \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    ros-${ROS_DISTRO}-turtlesim \
    && rm -rf /var/lib/apt/lists/*

# Set CycloneDDS as default RMW implementation (better local communication)
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

################################################################################
# 🐍 PYTHON DEPENDENCIES — the BTEng stack
#
# Installed system-wide with --break-system-packages (Ubuntu 24.04 requirement):
#   - bteng      : the pure-Python behavior tree engine
#   - bteng-ros2 : ROS 2 base classes + RosBTExecutor for BTEng
#   - pyzmq      : powers BTEng's ZmqPublisher live stream on port 2667
#
# (Equivalent to `pip install 'bteng[zmq]' bteng-ros2`.)
################################################################################
RUN pip3 install --break-system-packages bteng bteng-ros2 pyzmq

################################################################################
# 🖥️ X11 DISPLAY CONFIGURATION
#
# Purpose:
#   - Configure environment to suppress GUI warnings in container
#   - Required for running turtlesim's graphical window
#
# Settings:
#   - XDG_RUNTIME_DIR: Runtime directory for user services
#   - NO_AT_BRIDGE: Disable accessibility bridge warnings
#
# ⚠️ IMPORTANT: Before running GUI apps, execute on the HOST:
#   xhost +local:docker
################################################################################
RUN mkdir /tmp/runtime-root
ENV XDG_RUNTIME_DIR="/tmp/runtime-root"
RUN chmod -R 0700 /tmp/runtime-root
ENV NO_AT_BRIDGE=1

################################################################################
# 🚀 ENTRYPOINT SCRIPT
#
# Purpose:
#   - Auto-source ROS 2 and the /dev_ws overlay on container start
#   - Executed for both interactive shells and command execution
#
# Sources (in order):
#   1. /opt/ros/${ROS_DISTRO}/setup.bash (ROS 2 base)
#   2. /dev_ws/install/setup.bash        (development packages, if built)
################################################################################
COPY ./docker/entrypoint.sh /
RUN chmod +x /entrypoint.sh
ENTRYPOINT [ "/entrypoint.sh" ]

################################################################################
# 🛠️ STAGE 2: DEVELOPMENT IMAGE
#
# Purpose:
#   - Interactive development environment with non-root user
#   - Overlay workspace (/dev_ws) for project packages
#   - Volume mounts for live code editing (see docker-compose.yaml)
#
# Key Features:
#   - Non-root user with sudo access (security best practice)
#   - Persistent build artifacts via volume mounts
#   - Builds bt_turtlesim_interfaces + bt_turtlesim_ctrl with colcon
#   - All base dependencies inherited from the base stage
################################################################################
FROM base AS dev

################################################################################
# 👤 USER CONFIGURATION
#
# Build arguments (can be overridden via docker-compose or --build-arg):
#   - USERNAME: Development user name (default: devuser)
#   - UID: User ID (default: 1000, matches host user for file permissions)
#   - GID: Group ID (default: same as UID)
################################################################################
ARG USERNAME=devuser
ARG UID=1000
ARG GID=${UID}

################################################################################
# 🔧 DEVELOPMENT TOOLS
#
# Lightweight extras for editing/poking around inside the container.
################################################################################
RUN apt-get update && apt-get install -y --no-install-recommends \
    nano \
    && rm -rf /var/lib/apt/lists/*

################################################################################
# 👤 USER CREATION
#
# Process:
#   1. Remove pre-existing 'ubuntu' user (common in Ubuntu base images)
#   2. Create new user group with specified GID
#   3. Create new user with specified UID and home directory
#   4. Grant passwordless sudo privileges
#   5. Set proper ownership of home directory
################################################################################

# Handle pre-existing user with UID=1000 (common in Ubuntu images)
RUN id ubuntu 2>/dev/null \
   && (touch /var/mail/ubuntu \
   && chown ubuntu /var/mail/ubuntu \
   && userdel -r ubuntu) || true

# Create development user with sudo privileges
RUN groupadd --gid $GID $USERNAME \
    && useradd --uid ${GID} --gid ${UID} --create-home ${USERNAME} \
    && echo ${USERNAME} ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME} \
    && mkdir -p /home/${USERNAME} \
    && chown -R ${UID}:${GID} /home/${USERNAME}

################################################################################
# 📁 OVERLAY WORKSPACE: /dev_ws
#
# Purpose:
#   - Development workspace for project-specific packages
#   - Mounted as volume for live code editing (see docker-compose.yaml)
#
# Initial build (in image):
#   - Copies bt_turtlesim_interfaces + bt_turtlesim_ctrl packages
#   - Builds with colcon to verify everything compiles
#
# Runtime (with volume mounts):
#   - Source code mounted from host (live editing)
#   - Build artifacts in .colcon/ (persistent across container restarts)
#   - Rebuild with: colcon build --symlink-install
################################################################################
RUN mkdir -p /dev_ws/src
WORKDIR /dev_ws

# Copy project packages for initial build
COPY ./interfaces/        ./src/bt_turtlesim_interfaces/
COPY ./bt_turtlesim_ctrl/ ./src/bt_turtlesim_ctrl/

# Build overlay workspace (interfaces must be built before bt_turtlesim_ctrl)
RUN source /opt/ros/${ROS_DISTRO}/setup.bash \
    && apt-get update \
    && rosdep install --from-paths src --ignore-src --rosdistro ${ROS_DISTRO} -y \
    && rm -rf /var/lib/apt/lists/* \
    && colcon build --symlink-install

# Transfer dev workspace ownership to dev user
RUN chown -R ${UID}:${GID} /dev_ws/

################################################################################
# ✅ FINAL USER SETUP
#
# Steps:
#   1. Switch to non-root user for all subsequent operations
#   2. Auto-source entrypoint in .bashrc for interactive shells
#
# Entrypoint sourcing order:
#   - ROS 2 base environment
#   - Dev workspace (/dev_ws)
################################################################################
USER ${USERNAME}
RUN echo "source /entrypoint.sh" >> /home/${USERNAME}/.bashrc
