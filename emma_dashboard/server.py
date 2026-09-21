from __future__ import annotations

import asyncio
import fcntl
import json
import math
import os
import pty
import re
import signal
import socket
import struct
import subprocess
import termios
import threading
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


PROJECT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_DIR / "emma_dashboard" / "static"
NODE_MODULES_DIR = PROJECT_DIR / "node_modules"
ROUTES_DIR = Path(
    os.environ.get("EMMA_ROUTES_DIR", "/home/jetson/emma/src/carolina/routes")
)
NAV_MAPS_DIR = Path(
    os.environ.get("EMMA_NAV_MAPS_DIR", "/home/jetson/emma/src/carolina/maps")
)
NAV_MAP_CONFIG = Path(
    os.environ.get(
        "EMMA_NAV_MAP_CONFIG",
        "/home/jetson/emma/src/carolina/config/slam_localization.yaml",
    )
)
MAP_MANAGER = Path(
    os.environ.get("EMMA_MAP_MANAGER", "/home/jetson/emma/scripts/map_manager.py")
)
CONTROLLER_RESET_SCRIPT = Path(
    os.environ.get(
        "EMMA_CONTROLLER_RESET_SCRIPT",
        "/home/jetson/emma/scripts/controller_usb_reset_fast.sh",
    )
)

ORIN_HOST = os.environ.get("EMMA_ORIN_HOST", "192.168.68.72")
MEDIAMTX_API = os.environ.get("EMMA_MEDIAMTX_API", "http://127.0.0.1:9997")
VISION_DEVICES = {
    "astra": Path(
        "/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera_SN0001-video-index0"
    ),
    "arm": Path(
        "/dev/v4l/by-id/usb-icSpring_icspring_camera-video-index0"
    ),
}

MANAGED_SERVICES = {
    "nav": {
        "unit": "emma-nav.service",
        "label": "Nav2",
    },
    "patrol": {
        "unit": "emma-patrol.service",
        "label": "Patrol",
    },
    "vision": {
        "unit": "emma-vision.target",
        "label": "Vision",
    },
    "video": {
        "unit": "emma-video.service",
        "label": "Video WebRTC",
    },
    "depth": {
        "unit": "emma-astra-depth.service",
        "label": "Astra Depth",
    },
    "od_astra": {
        "unit": "emma-od-astra.service",
        "label": "OD Astra",
    },
    "od_arm": {
        "unit": "emma-od-arm.service",
        "label": "OD Arm Cam",
    },
    "isa": {
        "unit": "emma-isa.service",
        "label": "ISA + OD local",
    },
}
SERVICE_ACTIONS = {"start", "stop", "restart"}

PATROL_COMMANDS = {
    "start",
    "resume",
    "stop",
    "hold",
    "reload",
    "speed_slow_linear",
    "speed_normal_linear",
    "speed_fast_linear",
    "speed_slow_omni",
    "speed_normal_omni",
    "speed_fast_omni",
}
ISA_COMMANDS = {
    "auto",
    "next",
    "reset",
    "combo_test",
    "abort_bin",
    "bin_auto",
    "bin_override",
    "auto_joint",
    "joint_step",
    "drop",
    "pow_test",
    "grasp_ok",
    "grasp_fail",
    "uncertain",
    "profiler",
    "help",
    "a",
    "s",
    "r",
    "c",
    "k",
    "b",
    "t",
    "x",
    "y",
    "u",
    "o",
    "g",
    "f",
    "p",
    "h",
}
RECORDING_COMMANDS = {
    "start_both",
    "start_raw",
    "start_annotated",
    "save",
    "cancel",
}


def unix_time() -> float:
    return round(time.time(), 3)


def quaternion_yaw(orientation: Any) -> float:
    sin_yaw = 2.0 * (
        float(orientation.w) * float(orientation.z)
        + float(orientation.x) * float(orientation.y)
    )
    cos_yaw = 1.0 - 2.0 * (
        float(orientation.y) ** 2 + float(orientation.z) ** 2
    )
    return math.atan2(sin_yaw, cos_yaw)


def encode_grid_rle(values: Any) -> list[int]:
    encoded: list[int] = []
    previous: int | None = None
    count = 0

    for raw_value in values:
        value = int(raw_value)
        if previous is None:
            previous = value
            count = 1
        elif value == previous:
            count += 1
        else:
            encoded.extend((previous, count))
            previous = value
            count = 1

    if previous is not None:
        encoded.extend((previous, count))

    return encoded


def available_routes() -> list[str]:
    routes: list[tuple[int, str]] = []
    try:
        candidates = ROUTES_DIR.glob("route_*.json")
        for route_path in candidates:
            route_name = route_path.stem
            suffix = route_name.removeprefix("route_")
            if route_name.startswith("route_") and suffix.isdigit():
                routes.append((int(suffix), route_name))
    except OSError:
        return []
    return [route_name for _number, route_name in sorted(routes)]


def available_navigation_maps() -> list[str]:
    try:
        data_names = {path.stem for path in NAV_MAPS_DIR.glob("*.data")}
        posegraph_names = {
            path.stem for path in NAV_MAPS_DIR.glob("*.posegraph")
        }
    except OSError:
        return []
    return sorted(data_names & posegraph_names, key=str.casefold)


def active_navigation_map() -> str:
    active_map_file = NAV_MAPS_DIR / ".active_map"
    try:
        if active_map_file.is_file():
            active = active_map_file.read_text(encoding="utf-8").strip()
            if active:
                return Path(active).name

        match = re.search(
            r"^[ \t]*map_file_name:[ \t]*(.*?)[ \t]*$",
            NAV_MAP_CONFIG.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    except OSError:
        return ""

    if not match:
        return ""
    value = match.group(1).split("#", 1)[0].strip().strip("\"'")
    return Path(value).name


def local_websocket_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")

    if not origin:
        return True

    try:
        origin_host = urlparse(origin).hostname

        host_header = websocket.headers.get("host", "")
        request_host = urlparse(f"//{host_header}").hostname

        return origin_host in {
            "127.0.0.1",
            "localhost",
            "::1",
            request_host,
        }

    except ValueError:
        return False


class DashboardHub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[WebSocket] = set()
        self.events: deque[dict[str, Any]] = deque(maxlen=250)
        self._event_id = 0
        self.state: dict[str, Any] = {
            "connections": {
                "orin": False,
                "ros": False,
                "orin_host": ORIN_HOST,
                "updated_at": unix_time(),
            },
            "patrol": {
                "online": False,
                "status": "sin datos",
                "route": "--",
                "speed": "--",
                "waypoint_count": 0,
                "waypoint_index": -1,
                "nav_ready": False,
                "have_odom": False,
                "updated_at": 0,
            },
            "isa": {
                "online": False,
                "state": "sin datos",
                "mode": "--",
                "target": "--",
                "target_ready": False,
                "distance": None,
                "offset": None,
                "bin_active": False,
                "updated_at": 0,
            },
            "base": {
                "owner": "--",
                "state": "sin datos",
                "estop": False,
                "updated_at": 0,
            },
            "navigation": {
                "ready": False,
                "updated_at": 0,
            },
            "map": {
                "available": False,
                "revision": 0,
                "updated_at": 0,
            },
            "robot_pose": {
                "available": False,
                "frame_id": "map",
                "updated_at": 0,
            },
            "route": {
                "points": [],
                "updated_at": 0,
            },
            "vision": {
                "gateway_online": False,
                "astra_camera_connected": False,
                "arm_camera_connected": False,
                "astra_stream_ready": False,
                "arm_stream_ready": False,
                "webrtc_port": 8889,
                "updated_at": 0,
            },
            "od_astra": {
                "online": False,
                "alive": False,
                "detection_count": 0,
                "recording": False,
                "annotated_recording": False,
                "raw_recording": False,
                "recording_status_updated_at": 0,
                "updated_at": 0,
            },
            "od_arm": {
                "online": False,
                "alive": False,
                "recording": False,
                "annotated_recording": False,
                "raw_recording": False,
                "recording_status_updated_at": 0,
                "updated_at": 0,
            },
            "processes": {
                name: {
                    "name": name,
                    "label": config["label"],
                    "unit": config["unit"],
                    "load_state": "unknown",
                    "active_state": "unknown",
                    "sub_state": "unknown",
                    "updated_at": 0,
                }
                for name, config in MANAGED_SERVICES.items()
            },
        }

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "state": self.state,
            "events": list(self.events),
            "server_time": unix_time(),
        }

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)
        await websocket.send_json(self.snapshot())

    def disconnect(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in tuple(self.clients):
            try:
                await client.send_json(message)
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)

    async def update_section(self, section: str, values: dict[str, Any]) -> None:
        target = self.state.setdefault(section, {})
        target.update(values)
        await self.broadcast(
            {
                "type": "state",
                "section": section,
                "value": target,
                "server_time": unix_time(),
            }
        )

    async def add_event(
        self,
        source: str,
        message: str,
        level: str = "info",
    ) -> None:
        self._event_id += 1
        event = {
            "id": self._event_id,
            "time": unix_time(),
            "source": source,
            "level": level,
            "message": str(message).strip(),
        }
        self.events.appendleft(event)
        await self.broadcast({"type": "event", "event": event})

    def from_thread(self, coro: Any) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(coro, self.loop)


class RosBridge:
    def __init__(self, hub: DashboardHub) -> None:
        self.hub = hub
        self.node: Any = None
        self.executor: Any = None
        self.thread: threading.Thread | None = None
        self.publishers: dict[str, Any] = {}
        self.ready = False
        self.tf_buffer: Any = None
        self.tf_listener: Any = None
        self._time_class: Any = None
        self._map_revision = 0
        self._last_nav_ready: bool | None = None
        self._pose_available = False
        self._route_file_signature: tuple[str, int] | None = None
        self._last_patrol_status = ""
        self._last_rosout: dict[str, float] = {}

    def start(self) -> None:
        try:
            import rclpy
            from rcl_interfaces.msg import Log
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.qos import (
                DurabilityPolicy,
                QoSProfile,
                ReliabilityPolicy,
            )
            from rclpy.time import Time
            from geometry_msgs.msg import PoseWithCovarianceStamped
            from nav_msgs.msg import OccupancyGrid
            from std_msgs.msg import String
            from tf2_ros import Buffer, TransformListener
            from visualization_msgs.msg import MarkerArray

            if not rclpy.ok():
                rclpy.init(args=None)

            self.node = rclpy.create_node("emma_dashboard")
            self.publishers["patrol"] = self.node.create_publisher(
                String, "/patrol/cmd", 10
            )
            self.publishers["isa"] = self.node.create_publisher(
                String, "/isa/cmd", 10
            )
            self.publishers["record_astra"] = self.node.create_publisher(
                String, "/od/recording_cmd", 10
            )
            self.publishers["record_arm"] = self.node.create_publisher(
                String, "/arm_cam/recording_cmd", 10
            )
            self.publishers["initialpose"] = self.node.create_publisher(
                PoseWithCovarianceStamped, "/initialpose", 10
            )

            self.node.create_subscription(
                String, "/patrol/status", self._on_patrol_status, 10
            )
            self.node.create_subscription(
                String, "/patrol/status_json", self._on_patrol_json, 10
            )
            self.node.create_subscription(
                String, "/isa/status", self._on_isa_json, 10
            )
            self.node.create_subscription(
                String,
                "/od/video_status_json",
                self._on_od_video_status,
                10,
            )
            self.node.create_subscription(
                String,
                "/od/recording_status_json",
                self._on_od_recording_status,
                10,
            )
            self.node.create_subscription(
                String,
                "/od/inference_status_json",
                self._on_od_inference_status,
                10,
            )
            self.node.create_subscription(
                String,
                "/od/detection_frame_json",
                self._on_od_detection_frame,
                10,
            )
            self.node.create_subscription(
                String,
                "/object_distance_json",
                self._on_object_distance,
                10,
            )
            self.node.create_subscription(
                String,
                "/bin_alignment",
                self._on_bin_alignment,
                10,
            )
            self.node.create_subscription(
                String,
                "/arm_cam/video_status_json",
                self._on_arm_video_status,
                10,
            )
            self.node.create_subscription(
                String,
                "/arm_cam/recording_status_json",
                self._on_arm_recording_status,
                10,
            )
            self.node.create_subscription(
                String,
                "/alignment_command",
                self._on_arm_alignment,
                10,
            )
            self.node.create_subscription(
                String,
                "/arm_cam_bbox",
                self._on_arm_bbox,
                10,
            )
            self.node.create_subscription(
                String,
                "/arm_cam_stop",
                self._on_arm_stop,
                10,
            )
            self.node.create_subscription(
                String,
                "/arm_cam_grasp_verify",
                self._on_arm_grasp_verify,
                10,
            )

            map_qos = QoSProfile(depth=1)
            map_qos.reliability = ReliabilityPolicy.RELIABLE
            map_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
            self.node.create_subscription(
                OccupancyGrid,
                "/map",
                self._on_map,
                map_qos,
            )
            self.node.create_subscription(
                MarkerArray,
                "/patrol/markers",
                self._on_patrol_markers,
                10,
            )

            base_qos = QoSProfile(depth=10)
            base_qos.reliability = ReliabilityPolicy.RELIABLE
            base_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
            self.node.create_subscription(
                String,
                "/base/control/status",
                self._on_base_json,
                base_qos,
            )
            self.node.create_subscription(Log, "/rosout", self._on_rosout, 50)

            self.tf_buffer = Buffer()
            self.tf_listener = TransformListener(
                self.tf_buffer,
                self.node,
                spin_thread=False,
            )
            self._time_class = Time
            self.node.create_timer(0.2, self._update_robot_pose)
            self.node.create_timer(1.0, self._update_navigation_health)

            self.executor = MultiThreadedExecutor(num_threads=3)
            self.executor.add_node(self.node)
            self.thread = threading.Thread(
                target=self.executor.spin,
                name="emma-dashboard-ros",
                daemon=True,
            )
            self.thread.start()
            self.ready = True
            self.hub.from_thread(
                self.hub.update_section(
                    "connections", {"ros": True, "updated_at": unix_time()}
                )
            )
            self.hub.from_thread(
                self.hub.add_event("dashboard", "Puente ROS 2 listo", "ok")
            )
        except Exception as exc:
            self.ready = False
            self.hub.from_thread(
                self.hub.update_section(
                    "connections", {"ros": False, "updated_at": unix_time()}
                )
            )
            self.hub.from_thread(
                self.hub.add_event(
                    "dashboard", f"ROS 2 no disponible: {exc}", "error"
                )
            )

    def stop(self) -> None:
        if self.executor is not None:
            with suppress(Exception):
                self.executor.shutdown(timeout_sec=2.0)
        if self.node is not None:
            with suppress(Exception):
                self.node.destroy_node()
        try:
            import rclpy

            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        self.ready = False

    def publish(self, subsystem: str, command: str) -> bool:
        if not self.ready or subsystem not in self.publishers:
            return False
        try:
            from std_msgs.msg import String

            self.publishers[subsystem].publish(String(data=command))
            return True
        except Exception:
            return False

    def publish_initial_pose(
        self,
        x: float,
        y: float,
        yaw: float,
        frame_id: str = "map",
    ) -> bool:
        if not self.ready or "initialpose" not in self.publishers or self.node is None:
            return False
        try:
            from geometry_msgs.msg import PoseWithCovarianceStamped

            msg = PoseWithCovarianceStamped()
            msg.header.stamp = self.node.get_clock().now().to_msg()
            msg.header.frame_id = frame_id or "map"
            msg.pose.pose.position.x = float(x)
            msg.pose.pose.position.y = float(y)
            msg.pose.pose.position.z = 0.0
            msg.pose.pose.orientation.z = math.sin(float(yaw) / 2.0)
            msg.pose.pose.orientation.w = math.cos(float(yaw) / 2.0)
            msg.pose.covariance[0] = 0.25
            msg.pose.covariance[7] = 0.25
            msg.pose.covariance[35] = 0.06853891945200942
            self.publishers["initialpose"].publish(msg)
            return True
        except Exception:
            return False

    def _update_json(self, section: str, raw: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        payload["online"] = True
        payload["updated_at"] = unix_time()
        self.hub.from_thread(self.hub.update_section(section, payload))
        return payload

    def _on_patrol_status(self, msg: Any) -> None:
        status = str(msg.data).strip()
        self.hub.from_thread(
            self.hub.update_section(
                "patrol",
                {"online": True, "status": status, "updated_at": unix_time()},
            )
        )
        if status and status != self._last_patrol_status:
            self._last_patrol_status = status
            self.hub.from_thread(self.hub.add_event("patrol", status, "info"))

    def _on_patrol_json(self, msg: Any) -> None:
        payload = self._update_json("patrol", msg.data)
        if payload:
            self._load_route_file(str(payload.get("route", "")))

    def _on_isa_json(self, msg: Any) -> None:
        self._update_json("isa", msg.data)

    def _on_base_json(self, msg: Any) -> None:
        self._update_json("base", msg.data)

    def _on_od_video_status(self, msg: Any) -> None:
        self._update_json("od_astra", msg.data)

    def _update_recording_status(self, section: str, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        now = unix_time()
        payload.update(
            {
                "online": True,
                "recording_status_updated_at": now,
                "updated_at": now,
            }
        )
        self.hub.from_thread(self.hub.update_section(section, payload))

    def _on_od_recording_status(self, msg: Any) -> None:
        self._update_recording_status("od_astra", msg.data)

    def _on_od_inference_status(self, msg: Any) -> None:
        self._update_json("od_astra", msg.data)

    def _on_od_detection_frame(self, msg: Any) -> None:
        payload = self._parse_json(msg.data)
        if payload is None:
            return
        detections = payload.get("detections", [])
        compact = {
            "online": True,
            "detection_count": int(payload.get("detection_count", 0) or 0),
            "frame_id": int(payload.get("frame_id", 0) or 0),
            "frame_width": int(payload.get("frame_width", 0) or 0),
            "frame_height": int(payload.get("frame_height", 0) or 0),
            "detections": detections[:12] if isinstance(detections, list) else [],
            "updated_at": unix_time(),
        }
        self.hub.from_thread(self.hub.update_section("od_astra", compact))

    def _on_object_distance(self, msg: Any) -> None:
        payload = self._parse_json(msg.data)
        if payload is None:
            return
        self.hub.from_thread(
            self.hub.update_section(
                "od_astra",
                {
                    "target_distance_m": payload.get("distance"),
                    "target_offset": payload.get("x_offset"),
                    "target_class": payload.get("class_name", "--"),
                    "target_track_id": payload.get("track_id"),
                    "updated_at": unix_time(),
                },
            )
        )

    def _on_bin_alignment(self, msg: Any) -> None:
        payload = self._parse_json(msg.data)
        if payload is None:
            return
        self.hub.from_thread(
            self.hub.update_section(
                "od_astra",
                {
                    "bin_status": payload.get("status", "--"),
                    "bin_ready": bool(payload.get("ready", False)),
                    "bin_found": bool(payload.get("found", False)),
                    "updated_at": unix_time(),
                },
            )
        )

    def _on_arm_video_status(self, msg: Any) -> None:
        self._update_json("od_arm", msg.data)

    def _on_arm_recording_status(self, msg: Any) -> None:
        self._update_recording_status("od_arm", msg.data)

    def _on_arm_alignment(self, msg: Any) -> None:
        value = str(msg.data).strip()
        command, separator, angle = value.partition(":")
        try:
            angle_value = float(angle) if separator else None
        except ValueError:
            angle_value = None
        self.hub.from_thread(
            self.hub.update_section(
                "od_arm",
                {
                    "online": True,
                    "alignment_command": command or "--",
                    "alignment_angle": angle_value,
                    "updated_at": unix_time(),
                },
            )
        )

    def _on_arm_bbox(self, msg: Any) -> None:
        self._update_json("od_arm", msg.data)

    def _on_arm_stop(self, msg: Any) -> None:
        self.hub.from_thread(
            self.hub.update_section(
                "od_arm",
                {
                    "online": True,
                    "stop_signal": str(msg.data).strip(),
                    "updated_at": unix_time(),
                },
            )
        )

    def _on_arm_grasp_verify(self, msg: Any) -> None:
        payload = self._parse_json(msg.data)
        if payload is None:
            return
        self.hub.from_thread(
            self.hub.update_section(
                "od_arm",
                {
                    "grasp_state": payload.get("state", payload.get("status", "--")),
                    "grasp_reason": payload.get("reason", "--"),
                    "updated_at": unix_time(),
                },
            )
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _on_map(self, msg: Any) -> None:
        self._map_revision += 1
        info = msg.info
        origin = info.origin
        payload = {
            "available": True,
            "frame_id": str(msg.header.frame_id or "map"),
            "width": int(info.width),
            "height": int(info.height),
            "resolution": float(info.resolution),
            "origin": {
                "x": float(origin.position.x),
                "y": float(origin.position.y),
                "yaw": quaternion_yaw(origin.orientation),
            },
            "data_rle": encode_grid_rle(msg.data),
            "revision": self._map_revision,
            "updated_at": unix_time(),
        }
        self.hub.from_thread(self.hub.update_section("map", payload))

    def _on_patrol_markers(self, msg: Any) -> None:
        points: dict[int, dict[str, Any]] = {}

        for marker in msg.markers:
            if int(marker.action) == 3:
                points.clear()
                continue
            if int(marker.action) != 0:
                continue

            marker_id = int(marker.id)
            if marker.ns == "patrol_points":
                points[marker_id] = {
                    "x": round(float(marker.pose.position.x), 4),
                    "y": round(float(marker.pose.position.y), 4),
                    "yaw": 0.0,
                    "label": "",
                }
            elif marker.ns == "patrol_labels" and marker_id - 1 in points:
                points[marker_id - 1]["label"] = str(marker.text)
            elif marker.ns == "patrol_orientation" and marker_id - 2 in points:
                points[marker_id - 2]["yaw"] = round(
                    quaternion_yaw(marker.pose.orientation),
                    5,
                )

        ordered = [points[key] for key in sorted(points)]
        for index, point in enumerate(ordered, start=1):
            if not point["label"]:
                point["label"] = str(index)

        self.hub.from_thread(
            self.hub.update_section(
                "route",
                {
                    "points": ordered,
                    "updated_at": unix_time(),
                },
            )
        )

    def _load_route_file(self, route_name: str) -> None:
        suffix = route_name.removeprefix("route_")
        if not route_name.startswith("route_") or not suffix.isdigit():
            return

        route_path = ROUTES_DIR / f"{route_name}.json"
        try:
            signature = (route_name, route_path.stat().st_mtime_ns)
            if signature == self._route_file_signature:
                return
            route_data = json.loads(route_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        points: list[dict[str, Any]] = []
        bin_number = route_data.get("roles", {}).get("bin")
        for index, waypoint in enumerate(route_data.get("waypoints", []), start=1):
            try:
                qx = float(waypoint.get("qx", 0.0))
                qy = float(waypoint.get("qy", 0.0))
                qz = float(waypoint.get("qz", 0.0))
                qw = float(waypoint.get("qw", 1.0))
                yaw = math.atan2(
                    2.0 * (qw * qz + qx * qy),
                    1.0 - 2.0 * (qy * qy + qz * qz),
                )
                label = f"{index} BIN" if bin_number == index else str(index)
                points.append(
                    {
                        "x": round(float(waypoint["x"]), 4),
                        "y": round(float(waypoint["y"]), 4),
                        "yaw": round(yaw, 5),
                        "label": label,
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue

        self._route_file_signature = signature
        self.hub.from_thread(
            self.hub.update_section(
                "route",
                {
                    "name": route_name,
                    "points": points,
                    "updated_at": unix_time(),
                },
            )
        )

    def _update_robot_pose(self) -> None:
        if self.tf_buffer is None or self._time_class is None:
            return

        try:
            transform = self.tf_buffer.lookup_transform(
                "map",
                "base_footprint",
                self._time_class(),
            )
        except Exception:
            return

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        stamp = transform.header.stamp
        stamp_seconds = float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000
        if stamp_seconds > 0.0:
            now_seconds = self.node.get_clock().now().nanoseconds / 1_000_000_000
            if now_seconds - stamp_seconds > 2.5:
                if self._pose_available:
                    self._pose_available = False
                    self.hub.from_thread(
                        self.hub.update_section(
                            "robot_pose",
                            {
                                "available": False,
                                "updated_at": unix_time(),
                            },
                        )
                    )
                return

        self._pose_available = True
        self.hub.from_thread(
            self.hub.update_section(
                "robot_pose",
                {
                    "available": True,
                    "frame_id": "map",
                    "x": round(float(translation.x), 4),
                    "y": round(float(translation.y), 4),
                    "yaw": round(quaternion_yaw(rotation), 5),
                    "updated_at": unix_time(),
                },
            )
        )

    def _update_navigation_health(self) -> None:
        if self.node is None:
            return

        try:
            services = {
                name for name, _types in self.node.get_service_names_and_types()
            }
            ready = "/bt_navigator/get_state" in services
        except Exception:
            ready = False

        if ready == self._last_nav_ready:
            return

        self._last_nav_ready = ready
        self.hub.from_thread(
            self.hub.update_section(
                "navigation",
                {
                    "ready": ready,
                    "updated_at": unix_time(),
                },
            )
        )

    def _on_rosout(self, msg: Any) -> None:
        name = str(msg.name).lower()
        text = str(msg.msg).strip()
        interesting = (
            "isa" in name
            or "patrol" in name
            or "navigator" in name
            or "base_control" in name
            or "[isa]" in text.lower()
            or "[patrol]" in text.lower()
        )
        if not interesting or not text:
            return

        now = time.monotonic()
        dedupe_key = f"{name}:{text}"
        if now - self._last_rosout.get(dedupe_key, 0.0) < 2.0:
            return
        self._last_rosout[dedupe_key] = now
        if len(self._last_rosout) > 500:
            cutoff = now - 30.0
            self._last_rosout = {
                key: stamp
                for key, stamp in self._last_rosout.items()
                if stamp >= cutoff
            }

        level_number = int(msg.level)
        if level_number >= 40:
            level = "error"
        elif level_number >= 30:
            level = "warn"
        else:
            level = "info"
        source = "isa" if "isa" in name or "[isa]" in text.lower() else "patrol"
        self.hub.from_thread(self.hub.add_event(source, text, level))


hub = DashboardHub()
ros_bridge = RosBridge(hub)


class ServiceManager:
    def __init__(self, hub: DashboardHub) -> None:
        self.hub = hub
        self._last_states: dict[str, str] = {}

    async def _run(
        self,
        *command: str,
        timeout: float = 12.0,
    ) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return 124, "", "Tiempo de espera agotado"

        return (
            int(process.returncode or 0),
            stdout.decode(errors="replace").strip(),
            stderr.decode(errors="replace").strip(),
        )

    async def status(self, name: str) -> dict[str, Any]:
        config = MANAGED_SERVICES[name]
        unit = config["unit"]
        properties = (
            "LoadState,ActiveState,SubState,Result,MainPID,ExecMainStatus,"
            "ActiveEnterTimestampMonotonic"
        )
        code, stdout, stderr = await self._run(
            "systemctl",
            "--user",
            "show",
            unit,
            f"--property={properties}",
            "--no-pager",
        )
        values: dict[str, str] = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value

        active_since_us = int(
            values.get("ActiveEnterTimestampMonotonic", "0") or 0
        )
        uptime = 0.0
        if active_since_us:
            uptime = max(0.0, time.monotonic() - active_since_us / 1_000_000)

        return {
            "name": name,
            "label": config["label"],
            "unit": unit,
            "load_state": values.get("LoadState", "not-found"),
            "active_state": values.get("ActiveState", "unknown"),
            "sub_state": values.get("SubState", "unknown"),
            "result": values.get("Result", "unknown"),
            "main_pid": int(values.get("MainPID", "0") or 0),
            "exit_status": int(values.get("ExecMainStatus", "0") or 0),
            "uptime_sec": round(uptime, 1),
            "error": stderr if code and not stdout else "",
            "updated_at": unix_time(),
        }

    async def refresh(self, announce: bool = True) -> dict[str, Any]:
        results = await asyncio.gather(
            *(self.status(name) for name in MANAGED_SERVICES)
        )
        processes = {result["name"]: result for result in results}
        await self.hub.update_section("processes", processes)

        if announce:
            for name, status in processes.items():
                current = status["active_state"]
                previous = self._last_states.get(name)
                if previous is not None and previous != current:
                    level = "ok" if current == "active" else "warn"
                    await self.hub.add_event(
                        "systemd",
                        f"{status['label']}: {current}",
                        level,
                    )
                self._last_states[name] = current
        else:
            self._last_states = {
                name: status["active_state"] for name, status in processes.items()
            }

        return processes

    async def monitor(self) -> None:
        await self.refresh(announce=False)
        while True:
            await asyncio.sleep(2.0)
            await self.refresh()

    async def set_navigation_map(self, map_name: str) -> str:
        requested = map_name.strip()
        if not requested or Path(requested).name != requested:
            raise ValueError("Nombre de mapa no permitido")
        if requested not in available_navigation_maps():
            raise ValueError(f"Mapa de navegacion no disponible: {requested}")
        if not MAP_MANAGER.is_file():
            raise RuntimeError(f"No existe el gestor de mapas: {MAP_MANAGER}")

        code, stdout, stderr = await self._run(
            "python3",
            str(MAP_MANAGER),
            "set",
            requested,
            timeout=6.0,
        )
        if code:
            raise RuntimeError(stderr or stdout or "No se pudo activar el mapa")

        selected = stdout.splitlines()[-1].strip() if stdout else requested
        await self.hub.add_event(
            "systemd",
            f"Mapa Nav2: {selected}",
            "command",
        )
        return selected

    async def action(
        self,
        name: str,
        action: str,
        map_name: str | None = None,
    ) -> dict[str, Any]:
        if name not in MANAGED_SERVICES or action not in SERVICE_ACTIONS:
            raise ValueError("Accion de proceso no permitida")

        if map_name is not None:
            can_select_map = (
                name == "nav" and action in {"start", "restart"}
            ) or (
                name == "patrol"
                and action in {"start", "restart"}
            )
            if not can_select_map:
                raise ValueError("El mapa solo se selecciona al iniciar Nav2")

            nav_status = await self.status("nav")
            nav_active = nav_status["active_state"] in {
                "active",
                "activating",
                "reloading",
            }
            if name == "patrol" and nav_active:
                if map_name != active_navigation_map():
                    raise ValueError(
                        "Nav2 ya esta activo; reinicialo para cambiar de mapa"
                    )
            else:
                await self.set_navigation_map(map_name)

        unit = MANAGED_SERVICES[name]["unit"]
        if name == "vision" and action in {"stop", "restart"}:
            vision_units = (
                MANAGED_SERVICES["isa"]["unit"],
                MANAGED_SERVICES["od_arm"]["unit"],
                MANAGED_SERVICES["od_astra"]["unit"],
                MANAGED_SERVICES["depth"]["unit"],
                MANAGED_SERVICES["video"]["unit"],
                unit,
            )
            code, _stdout, stderr = await self._run(
                "systemctl",
                "--user",
                "stop",
                *vision_units,
                timeout=20.0,
            )
            if code:
                raise RuntimeError(
                    stderr or f"systemctl termino con codigo {code}"
                )
            if action == "stop":
                await self.hub.add_event(
                    "systemd",
                    "Vision: stop",
                    "command",
                )
                await asyncio.sleep(0.2)
                return await self.status(name)

        code, _stdout, stderr = await self._run(
            "systemctl",
            "--user",
            "--no-block",
            action,
            unit,
        )
        if code:
            raise RuntimeError(stderr or f"systemctl termino con codigo {code}")

        await self.hub.add_event(
            "systemd",
            f"{MANAGED_SERVICES[name]['label']}: {action}",
            "command",
        )
        await asyncio.sleep(0.2)
        return await self.status(name)

    async def logs(self, name: str, lines: int) -> str:
        if name not in MANAGED_SERVICES:
            raise ValueError("Proceso no permitido")

        unit = MANAGED_SERVICES[name]["unit"]
        code, stdout, stderr = await self._run(
            "journalctl",
            f"--user-unit={unit}",
            "--lines",
            str(max(20, min(lines, 400))),
            "--no-pager",
            "--output=short-iso",
        )
        if code:
            raise RuntimeError(stderr or "No se pudieron leer los logs")
        return stdout


service_manager = ServiceManager(hub)


def probe_mediamtx() -> dict[str, Any]:
    request = Request(
        f"{MEDIAMTX_API.rstrip('/')}/v3/paths/list",
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=1.5) as response:
            payload = json.load(response)
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return {"online": False, "paths": {}}

    paths: dict[str, dict[str, Any]] = {}
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        if name in {"astra", "arm"}:
            paths[name] = {
                "ready": bool(item.get("ready", False)),
                "bytes_received": int(item.get("bytesReceived", 0) or 0),
                "readers": len(item.get("readers", []) or []),
            }
    return {"online": True, "paths": paths}


class VisionMonitor:
    def __init__(self, hub: DashboardHub) -> None:
        self.hub = hub
        self._previous: tuple[bool, bool, bool] | None = None

    async def refresh(self, announce: bool = True) -> dict[str, Any]:
        media = await asyncio.to_thread(probe_mediamtx)
        paths = media.get("paths", {})
        astra_path = paths.get("astra", {})
        arm_path = paths.get("arm", {})
        values = {
            "gateway_online": bool(media.get("online", False)),
            "astra_camera_connected": VISION_DEVICES["astra"].exists(),
            "arm_camera_connected": VISION_DEVICES["arm"].exists(),
            "astra_stream_ready": bool(astra_path.get("ready", False)),
            "arm_stream_ready": bool(arm_path.get("ready", False)),
            "astra_bytes_received": int(astra_path.get("bytes_received", 0)),
            "arm_bytes_received": int(arm_path.get("bytes_received", 0)),
            "astra_readers": int(astra_path.get("readers", 0)),
            "arm_readers": int(arm_path.get("readers", 0)),
            "webrtc_port": 8889,
            "updated_at": unix_time(),
        }
        await self.hub.update_section("vision", values)

        current = (
            values["gateway_online"],
            values["astra_stream_ready"],
            values["arm_stream_ready"],
        )
        if announce and self._previous is not None:
            labels = ("Gateway WebRTC", "Stream Astra", "Stream Arm Cam")
            for index, (before, now) in enumerate(zip(self._previous, current)):
                if before != now:
                    await self.hub.add_event(
                        "vision",
                        f"{labels[index]}: {'online' if now else 'offline'}",
                        "ok" if now else "warn",
                    )
        self._previous = current
        return values

    async def monitor(self) -> None:
        await self.refresh(announce=False)
        while True:
            await asyncio.sleep(2.0)
            await self.refresh()


vision_monitor = VisionMonitor(hub)


def probe_orin() -> bool:
    try:
        with socket.create_connection((ORIN_HOST, 22), timeout=1.5):
            return True
    except OSError:
        return False


async def monitor_connections() -> None:
    previous: bool | None = None
    while True:
        online = await asyncio.to_thread(probe_orin)
        await hub.update_section(
            "connections", {"orin": online, "updated_at": unix_time()}
        )
        if previous is not None and online != previous:
            await hub.add_event(
                "orin",
                "Conexion SSH disponible" if online else "Orin no responde por SSH",
                "ok" if online else "warn",
            )
        previous = online
        await asyncio.sleep(5.0)


@asynccontextmanager
async def lifespan(_: FastAPI):
    hub.bind_loop(asyncio.get_running_loop())
    ros_bridge.start()
    monitor_task = asyncio.create_task(monitor_connections())
    service_task = asyncio.create_task(service_manager.monitor())
    vision_task = asyncio.create_task(vision_monitor.monitor())
    try:
        yield
    finally:
        monitor_task.cancel()
        service_task.cancel()
        vision_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        with suppress(asyncio.CancelledError):
            await service_task
        with suppress(asyncio.CancelledError):
            await vision_task
        ros_bridge.stop()


app = FastAPI(title="EMMA Dashboard", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount(
    "/vendor",
    StaticFiles(directory=NODE_MODULES_DIR, check_dir=False),
    name="vendor",
)


class CommandBody(BaseModel):
    subsystem: str
    command: str


class ProcessActionBody(BaseModel):
    map: str | None = None


class InitialPoseBody(BaseModel):
    x: float
    y: float
    yaw: float
    frame_id: str = "map"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return hub.snapshot()


@app.get("/api/routes")
async def routes() -> dict[str, Any]:
    return {"ok": True, "routes": available_routes()}


@app.get("/api/navigation/maps")
async def navigation_maps() -> dict[str, Any]:
    return {
        "ok": True,
        "maps": available_navigation_maps(),
        "active": active_navigation_map(),
    }


@app.get("/api/vision")
async def vision_status() -> dict[str, Any]:
    return {"ok": True, "vision": await vision_monitor.refresh(False)}


@app.post("/api/command")
async def command(body: CommandBody) -> dict[str, Any]:
    subsystem = body.subsystem.strip().lower()
    requested = body.command.strip().lower()
    if subsystem == "patrol":
        allowed = requested in PATROL_COMMANDS or requested in available_routes()
    elif subsystem == "isa":
        allowed = requested in ISA_COMMANDS
    else:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=400, detail="Comando no permitido")
    if not ros_bridge.publish(subsystem, requested):
        raise HTTPException(status_code=503, detail="Puente ROS 2 no disponible")
    await hub.add_event(subsystem, f"CMD -> {requested}", "command")
    return {"ok": True, "subsystem": subsystem, "command": requested}


@app.post("/api/recordings/{camera}/{recording_command}")
async def recording_action(camera: str, recording_command: str) -> dict[str, Any]:
    requested_camera = camera.strip().lower()
    requested_command = recording_command.strip().lower()
    if requested_camera not in {"astra", "arm"}:
        raise HTTPException(status_code=400, detail="Camara no permitida")
    if requested_command not in RECORDING_COMMANDS:
        raise HTTPException(status_code=400, detail="Comando de grabacion no permitido")
    publisher = f"record_{requested_camera}"
    if not ros_bridge.publish(publisher, requested_command):
        raise HTTPException(status_code=503, detail="Puente ROS 2 no disponible")
    await hub.add_event(
        "vision",
        f"REC {requested_camera.upper()} -> {requested_command}",
        "command",
    )
    return {
        "ok": True,
        "camera": requested_camera,
        "command": requested_command,
    }


@app.get("/api/processes")
async def processes() -> dict[str, Any]:
    return {"ok": True, "processes": await service_manager.refresh(False)}


@app.post("/api/processes/{name}/{action}")
async def process_action(
    name: str,
    action: str,
    body: ProcessActionBody | None = None,
) -> dict[str, Any]:
    requested_name = name.strip().lower()
    requested_action = action.strip().lower()
    try:
        status = await service_manager.action(
            requested_name,
            requested_action,
            body.map if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "process": status,
        "action": requested_action,
        "navigation_map": active_navigation_map(),
    }


@app.get("/api/processes/{name}/logs")
async def process_logs(name: str, lines: int = 160) -> dict[str, Any]:
    requested_name = name.strip().lower()
    try:
        logs = await service_manager.logs(requested_name, lines)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "name": requested_name, "logs": logs}


@app.post("/api/navigation/initial-pose")
async def navigation_initial_pose(body: InitialPoseBody) -> dict[str, Any]:
    frame_id = body.frame_id.strip() or "map"
    if frame_id != "map":
        raise HTTPException(status_code=400, detail="Frame no permitido")
    if not ros_bridge.publish_initial_pose(body.x, body.y, body.yaw, frame_id):
        raise HTTPException(status_code=503, detail="Puente ROS 2 no disponible")
    await hub.add_event(
        "navigation",
        f"Initial pose -> x={body.x:.2f} y={body.y:.2f} yaw={math.degrees(body.yaw):.0f}deg",
        "command",
    )
    return {
        "ok": True,
        "x": body.x,
        "y": body.y,
        "yaw": body.yaw,
        "frame_id": frame_id,
    }


@app.post("/api/emergency/controller-reset")
async def controller_emergency_reset() -> dict[str, Any]:
    if not CONTROLLER_RESET_SCRIPT.exists():
        raise HTTPException(status_code=503, detail="Script C33 no encontrado")

    code, stdout, stderr = await service_manager._run(
        str(CONTROLLER_RESET_SCRIPT),
        timeout=18.0,
    )
    output = "\n".join(part for part in (stdout, stderr) if part).strip()
    if code != 0:
        await hub.add_event(
            "system",
            f"C33 fallo rc={code}: {output[-240:] if output else 'sin salida'}",
            "error",
        )
        raise HTTPException(
            status_code=503,
            detail=output or f"C33 fallo con codigo {code}",
        )

    await hub.add_event("system", "C33 controller reset ejecutado", "warn")
    return {"ok": True, "output": output}


@app.websocket("/ws/state")
async def state_socket(websocket: WebSocket) -> None:
    if not local_websocket_origin(websocket):
        await websocket.close(code=1008)
        return
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)


def set_pty_size(fd: int, cols: int, rows: int) -> None:
    cols = max(20, int(cols))
    rows = max(8, int(rows))

    winsize = struct.pack(
        "HHHH",
        rows,
        cols,
        0,
        0,
    )

    fcntl.ioctl(
        fd,
        termios.TIOCSWINSZ,
        winsize,
    )


def open_local_terminal(cols: int, rows: int) -> tuple[Any, int]:
    master_fd, slave_fd = pty.openpty()

    set_pty_size(
        slave_fd,
        cols,
        rows,
    )

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env.setdefault("COLORTERM", "truecolor")

    process = subprocess.Popen(
        ["/bin/bash", "-i"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(Path.home()),
        env=env,
        start_new_session=True,
        close_fds=True,
    )

    os.close(slave_fd)

    os.set_blocking(
        master_fd,
        False,
    )

    return process, master_fd


async def pump_terminal_output(
    websocket: WebSocket,
    process: Any,
    master_fd: int,
) -> None:

    await websocket.send_json(
        {
            "type": "status",
            "value": "connected",
        }
    )

    while process.poll() is None:

        try:
            data = os.read(
                master_fd,
                8192,
            )

        except BlockingIOError:
            await asyncio.sleep(0.01)
            continue

        except OSError:
            break

        if not data:
            await asyncio.sleep(0.01)
            continue

        await websocket.send_bytes(data)


@app.websocket("/ws/terminal")
async def terminal_socket(websocket: WebSocket) -> None:

    if not local_websocket_origin(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    process: Any = None
    master_fd: int | None = None
    output_task: asyncio.Task[Any] | None = None

    try:
        await websocket.send_json(
            {
                "type": "status",
                "value": "connecting",
            }
        )

        process, master_fd = await asyncio.to_thread(
            open_local_terminal,
            120,
            32,
        )

        output_task = asyncio.create_task(
            pump_terminal_output(
                websocket,
                process,
                master_fd,
            )
        )

        while True:
            raw = await websocket.receive_text()

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            message_type = message.get("type")

            if message_type == "input":

                data = str(
                    message.get("data", "")
                ).encode()

                os.write(
                    master_fd,
                    data,
                )

            elif message_type == "resize":

                cols = max(
                    20,
                    int(message.get("cols", 120)),
                )

                rows = max(
                    8,
                    int(message.get("rows", 32)),
                )

                set_pty_size(
                    master_fd,
                    cols,
                    rows,
                )

    except WebSocketDisconnect:
        pass

    except Exception as exc:

        with suppress(Exception):
            await websocket.send_json(
                {
                    "type": "status",
                    "value": "error",
                    "message": str(exc),
                }
            )

    finally:

        if output_task is not None:
            output_task.cancel()

            with suppress(
                asyncio.CancelledError,
                Exception,
            ):
                await output_task

        if master_fd is not None:
            with suppress(Exception):
                os.close(master_fd)

        if process is not None and process.poll() is None:

            with suppress(Exception):
                os.killpg(
                    process.pid,
                    signal.SIGHUP,
                )

            try:
                await asyncio.to_thread(
                    process.wait,
                    1.0,
                )

            except subprocess.TimeoutExpired:

                with suppress(Exception):
                    os.killpg(
                        process.pid,
                        signal.SIGKILL,
                    )
