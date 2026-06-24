#!/bin/bash
# 🐢 Enhanced entrypoint for the Turtlesim BTEng ROS 2 container.

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Unicode glyphs
CHECK="✅"
CROSS="❌"
INFO="ℹ️ "

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}   🐢 Turtlesim BTEng Control — Dev Environment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Source ROS 2
if source /opt/ros/${ROS_DISTRO}/setup.bash 2>/dev/null; then
  echo -e "${CHECK} ${GREEN}Sourced ROS 2 ${ROS_DISTRO}${NC}"
else
  echo -e "${CROSS} ${RED}Failed to source ROS 2 ${ROS_DISTRO}${NC}"
fi

# Source the dev workspace, if built
if [ -f /dev_ws/install/setup.bash ]; then
  if source /dev_ws/install/setup.bash 2>/dev/null; then
    echo -e "${CHECK} ${GREEN}Sourced dev workspace: /dev_ws${NC}"
  else
    echo -e "${CROSS} ${RED}Failed to source dev workspace: /dev_ws${NC}"
  fi
else
  echo -e "${INFO}${YELLOW}Dev workspace not built yet: /dev_ws — run 'colcon build --symlink-install'${NC}"
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Ready! ${NC}Type your commands below or run:"
echo -e "  ${BLUE}colcon build --symlink-install${NC}"
echo -e "  ${BLUE}ros2 launch bt_turtlesim_ctrl turtlesim_bt.launch.py${NC}"
echo ""
echo -e "${INFO}${YELLOW}BTEng live stream: ZmqPublisher on tcp://*:1667 (host net) — pip install 'bteng[zmq]'${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Execute the command passed into this entrypoint
exec "$@"
