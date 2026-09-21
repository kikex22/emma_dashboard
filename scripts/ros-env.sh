#!/usr/bin/env bash

source /opt/ros/humble/setup.bash

if [[ -f /home/jetson/Documents/orbbec_ws/install/setup.bash ]]; then
  source /home/jetson/Documents/orbbec_ws/install/setup.bash
fi

source /home/jetson/emma/install/setup.bash

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-99}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file:///home/jetson/.ros/cyclonedds.xml}"
export PYTHONUNBUFFERED=1

unset ROS_LOCALHOST_ONLY
