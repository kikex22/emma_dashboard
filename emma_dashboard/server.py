from __future__ import annotations

import asyncio
import fcntl
import json
import math
import os
import pty
import re
import signal
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
from pydantic import BaseModel, Field


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
TEGRASTATS_BIN = Path(os.environ.get("EMMA_TEGRASTATS_BIN", "/usr/bin/tegrastats"))
EVALUATION_ROOT = Path(
    os.environ.get("EMMA_EVALUATION_DIR", "/home/jetson/.emma/evaluation")
)
EVALUATION_SCRIPT = Path(
    os.environ.get("EMMA_EVALUATION_SCRIPT", "/home/jetson/emma/scripts/evaluation.sh")
)
ROS_DIAGNOSTICS_LOG = Path(
    os.environ.get(
        "EMMA_ROS_DIAGNOSTICS_LOG",
        "/home/jetson/.emma/dashboard/ros_diagnostics.jsonl",
    )
)
ARM_CONFIG_DIRS = [
    Path(os.environ.get("EMMA_ARM_INSTALL_CONFIG_DIR", "/home/jetson/emma/install/emma_arm/share/emma_arm/config")),
    Path(os.environ.get("EMMA_ARM_SOURCE_CONFIG_DIR", "/home/jetson/emma/src/emma_arm/config")),
]

ORIN_HOST = os.environ.get("EMMA_ORIN_HOST", "orin")
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
    "arm": {
        "unit": "emma-arm.service",
        "label": "Brazo",
    },
    "evaluation": {
        "unit": "emma-evaluation.service",
        "label": "Evaluation",
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
ARM_DIRECT_COMMANDS = {
    "start",
    "home",
    "gripper_open",
    "gripper_close",
    "stop",
}
RECORDING_COMMANDS = {
    "start_both",
    "start_raw",
    "start_annotated",
    "save",
    "cancel",
}

EVALUATION_TYPES = {
    "slam_mapping": {
        "number": 3,
        "module": "carolina",
        "label": "SLAM / creacion de mapa",
        "suffix": "slam",
    },
    "nav_slam": {
        "number": 4,
        "module": "carolina",
        "label": "Nav2 / navegacion sobre mapa",
        "suffix": "nav",
    },
    "od_live": {
        "number": 5,
        "module": "vision",
        "label": "OD / deteccion en vivo",
        "suffix": "od",
    },
    "isa_mission": {
        "number": 8,
        "module": "isa",
        "label": "ISA mision completa",
        "suffix": "isa",
    },
    "video_stream": {
        "number": 9,
        "module": "vision",
        "label": "Video / streaming",
        "suffix": "video",
    },
}
EVALUATION_CLASSES = {"bottle", "can", "cup", "bin"}
EVALUATION_CAMERAS = {"astra", "arm_cam"}

# EMMA usa pack 3S: 11.1 V nominal, ~12.6 V cargada.
BATTERY_CELL_COUNT = int(os.environ.get("EMMA_BATTERY_CELLS", "3"))
BATTERY_EMA_ALPHA = float(os.environ.get("EMMA_BATTERY_EMA_ALPHA", "0.15"))
BATTERY_CELL_CURVE = (
    (4.20, 100),
    (4.15, 95),
    (4.11, 90),
    (4.02, 80),
    (3.95, 70),
    (3.87, 60),
    (3.84, 50),
    (3.80, 40),
    (3.77, 30),
    (3.73, 20),
    (3.69, 10),
    (3.50, 0),
)


def battery_percent_from_voltage(pack_voltage: float) -> int:
    if BATTERY_CELL_COUNT <= 0:
        return 0
    cell_voltage = pack_voltage / BATTERY_CELL_COUNT
    if cell_voltage >= BATTERY_CELL_CURVE[0][0]:
        return 100
    if cell_voltage <= BATTERY_CELL_CURVE[-1][0]:
        return 0
    for (high_v, high_pct), (low_v, low_pct) in zip(
        BATTERY_CELL_CURVE, BATTERY_CELL_CURVE[1:]
    ):
        if low_v <= cell_voltage <= high_v:
            span = high_v - low_v
            ratio = 0.0 if span <= 0 else (cell_voltage - low_v) / span
            pct = low_pct + ratio * (high_pct - low_pct)
            return max(0, min(100, int(pct + 0.5)))
    return 0


def unix_time() -> float:
    return round(time.time(), 3)


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def evaluation_active_state() -> dict[str, Any]:
    active = read_json_file(EVALUATION_ROOT / "active_trial.json")
    run_path = Path(str(active.get("path", "")))
    metadata = read_json_file(run_path / "metadata.json") if run_path.is_dir() else {}
    if not active or not metadata:
        return {
            "active": False,
            "run_id": "",
            "run_path": "",
            "started_at": "",
            "trial_type": "",
            "trial_type_label": "",
            "name": "",
            "location": "",
            "operator": "",
        }
    return {
        "active": True,
        "run_id": str(active.get("run_id", metadata.get("run_id", ""))),
        "run_path": str(run_path),
        "started_at": str(active.get("started_at", metadata.get("started_at", ""))),
        "trial_type": str(metadata.get("trial_type", "")),
        "trial_type_label": str(metadata.get("trial_type_label", "")),
        "name": str(metadata.get("name", "")),
        "location": str(metadata.get("location", "")),
        "operator": str(metadata.get("operator", "")),
        "notes": str(metadata.get("notes", "")),
        "od_scene_mode": str(metadata.get("od_scene_mode", "")),
        "od_expected_classes": list(metadata.get("od_expected_classes", []) or []),
        "od_expected_cameras": list(metadata.get("od_expected_cameras", []) or []),
    }


def evaluation_reports(limit: int = 12) -> list[dict[str, Any]]:
    runs_dir = EVALUATION_ROOT / "runs"
    try:
        run_paths = sorted(
            (path for path in runs_dir.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
    except OSError:
        return []

    reports: list[dict[str, Any]] = []
    for run_path in run_paths:
        metadata = read_json_file(run_path / "metadata.json")
        report = read_json_file(run_path / "report.json")
        if not metadata and not report:
            continue
        reports.append(
            {
                "run_id": run_path.name,
                "name": str(metadata.get("name", run_path.name)),
                "trial_type": str(metadata.get("trial_type", report.get("trial_type", ""))),
                "trial_type_label": str(
                    metadata.get("trial_type_label", report.get("trial_type_label", ""))
                ),
                "location": str(metadata.get("location", "")),
                "started_at": str(metadata.get("started_at", "")),
                "stopped_at": str(metadata.get("stopped_at", "")),
                "duration_sec": metadata.get("duration_sec"),
                "complete": bool(report),
                "counts": dict(report.get("counts", {}) or {}),
            }
        )
        if len(reports) >= max(1, min(limit, 50)):
            break
    return reports


def automatic_evaluation_name(location: str, trial_type: str) -> str:
    config = EVALUATION_TYPES[trial_type]
    safe_location = re.sub(r"[^a-z0-9]+", "_", location.strip().lower()).strip("_") or "otro"
    suffix = str(config["suffix"])
    pattern = re.compile(rf"^{re.escape(safe_location)}_(\d+)_{re.escape(suffix)}$")
    highest = 0
    runs_dir = EVALUATION_ROOT / "runs"
    try:
        paths = runs_dir.iterdir()
    except OSError:
        paths = ()
    for path in paths:
        metadata = read_json_file(path / "metadata.json")
        match = pattern.match(str(metadata.get("name", "")).lower())
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{safe_location}_{highest + 1}_{suffix}"


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


ARM_POSE_GROUPS = {
    "bottle": {
        "label": "Bottle",
        "poses": [
            ("bottle.pre_grasp", "pre lateral"),
            ("bottle.grip", "cerrar"),
            ("bottle.lift", "elevar"),
            ("bottle.full_lift", "full lift"),
            ("bottle.front_ready", "ready frontal"),
            ("bottle.front_pick", "pick frontal"),
            ("bottle.front_lift", "lift frontal"),
        ],
    },
    "can": {
        "label": "Can",
        "poses": [
            ("can.pre_grasp", "pre lateral"),
            ("can.grip", "cerrar"),
            ("can.lift", "elevar"),
            ("can.full_lift", "full lift"),
            ("can.front_ready", "ready frontal"),
            ("can.front_pick", "pick frontal"),
            ("can.front_lift", "lift frontal"),
        ],
    },
    "cup": {
        "label": "Cup",
        "poses": [
            ("cup.pre_grasp", "pre lateral"),
            ("cup.grip", "cerrar"),
            ("cup.lift", "elevar"),
            ("cup.full_lift", "full lift"),
            ("cup.front_ready", "ready frontal"),
            ("cup.front_pick", "pick frontal"),
            ("cup.front_lift", "lift frontal"),
        ],
    },
    "legacy": {
        "label": "C3 legacy",
        "poses": [
            ("start", "start"),
            ("start_center", "start center"),
            ("home", "home"),
            ("lateral_log_pre", "lateral pre"),
            ("lateral_grip", "cerrar lateral"),
            ("lateral_log_lift", "lateral lift"),
            ("minican_pre_lift", "minican pre"),
            ("cup_pre_lift", "cup pre"),
            ("bottle_lift", "bottle lift"),
            ("pow", "pow ready"),
            ("pow_pick", "pow pick"),
            ("pow_lift", "pow lift"),
            ("bin", "bin"),
            ("drop", "drop / abrir"),
            ("side_drop", "side drop"),
        ],
    },
}


def load_arm_pose_catalog() -> dict[str, Any]:
    def load_yaml(path: Path) -> dict[str, Any]:
        try:
            import yaml

            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    poses: dict[str, Any] = {}
    source_dir = ""
    for config_dir in ARM_CONFIG_DIRS:
        if not config_dir.is_dir():
            continue
        loaded: dict[str, Any] = {}
        main_file = config_dir / "bottle_pick_pose.yaml"
        if main_file.is_file():
            loaded.update(load_yaml(main_file))
        poses_dir = config_dir / "poses"
        if poses_dir.is_dir():
            for pose_file in sorted(poses_dir.glob("*.yaml")):
                loaded.update(load_yaml(pose_file))
        if loaded:
            poses = loaded
            source_dir = str(config_dir)
            break

    groups: list[dict[str, Any]] = []
    for group_id, config in ARM_POSE_GROUPS.items():
        items = [
            {
                "name": pose_name,
                "label": label,
                "available": pose_name in poses,
                "duration_ms": poses.get(pose_name, {}).get("duration_ms")
                or poses.get(pose_name, {}).get("speed_ms"),
            }
            for pose_name, label in config["poses"]
        ]
        groups.append({"id": group_id, "label": config["label"], "poses": items})
    return {
        "source": source_dir,
        "poses": sorted(poses),
        "groups": groups,
        "updated_at": unix_time(),
    }


ARM_POSE_CATALOG = load_arm_pose_catalog()


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
            "ros_diagnostics": {
                "status": "starting",
                "message": "Iniciando puente ROS 2",
                "executor_alive": False,
                "executor_age_sec": None,
                "topics": {},
                "tf": {},
                "network": [],
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
            "arm": {
                "online": False,
                "core_online": False,
                "poses_online": False,
                "teleop_online": False,
                "controller_service": False,
                "controller_connected": False,
                "controller_message": "",
                "last_command": "",
                "last_joint": None,
                "last_pulse": None,
                "ready_reason": "Servicio detenido",
                "pose_catalog": ARM_POSE_CATALOG,
                "updated_at": 0,
            },
            "battery": {
                "online": False,
                "raw_mv": None,
                "voltage_v": None,
                "filtered_voltage_v": None,
                "cell_voltage_v": None,
                "percent": None,
                "updated_at": 0,
            },
            "base": {
                "owner": "--",
                "state": "sin datos",
                "estop": False,
                "updated_at": 0,
            },
            "orin_health": {
                "online": False,
                "source": "tegrastats",
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
            "evaluation": {
                "active": False,
                "collector_online": False,
                "run_id": "",
                "run_path": "",
                "trial_type": "",
                "trial_type_label": "",
                "name": "",
                "location": "",
                "operator": "",
                "started_at": "",
                "interventions": 0,
                "seen_topics": 0,
                "clock_synchronized": time.time() > 1_600_000_000,
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
        self._diagnostic_lock = threading.Lock()
        self._started_at = unix_time()
        self._executor_heartbeat = 0.0
        self._topic_seen: dict[str, float] = {}
        self._tf_links: dict[str, dict[str, Any]] = {}
        self._last_tf_probe = 0.0
        self._publications: dict[str, dict[str, Any]] = {}
        self._arm_connection_client: Any = None
        self._arm_connection_future: Any = None
        self._battery_voltage_ema: float | None = None

    def _heartbeat(self) -> None:
        with self._diagnostic_lock:
            self._executor_heartbeat = unix_time()

    def _touch_topic(self, name: str) -> None:
        with self._diagnostic_lock:
            self._topic_seen[name] = unix_time()

    def _record_publication(
        self,
        subsystem: str,
        command: str,
        success: bool,
        error: str = "",
    ) -> None:
        publisher = self.publishers.get(subsystem)
        subscribers = 0
        if publisher is not None:
            with suppress(Exception):
                subscribers = int(publisher.get_subscription_count())
        record = {
            "record_type": "publication",
            "subsystem": subsystem,
            "command": command[:240],
            "success": success,
            "subscribers": subscribers,
            "error": error[:240],
            "recorded_at": unix_time(),
        }
        with self._diagnostic_lock:
            self._publications[subsystem] = dict(record)
        append_ros_diagnostic(record)

    def _probe_tf_links(self) -> None:
        if self.tf_buffer is None or self._time_class is None or self.node is None:
            return
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_tf_probe < 1.0:
            return
        self._last_tf_probe = now_monotonic
        now_ros = self.node.get_clock().now().nanoseconds / 1_000_000_000
        probes = {
            "map_odom": ("map", "odom"),
            "odom_base": ("odom", "base_footprint"),
            "map_base": ("map", "base_footprint"),
        }
        results: dict[str, dict[str, Any]] = {}
        for name, (target, source) in probes.items():
            try:
                transform = self.tf_buffer.lookup_transform(
                    target,
                    source,
                    self._time_class(),
                )
                stamp = transform.header.stamp
                stamp_seconds = float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000
                results[name] = {
                    "ok": True,
                    "target": target,
                    "source": source,
                    "age_sec": round(max(0.0, now_ros - stamp_seconds), 3)
                    if stamp_seconds > 0.0
                    else 0.0,
                    "error": "",
                    "checked_at": unix_time(),
                }
            except Exception as exc:
                results[name] = {
                    "ok": False,
                    "target": target,
                    "source": source,
                    "age_sec": None,
                    "error": f"{type(exc).__name__}: {exc}"[:240],
                    "checked_at": unix_time(),
                }
        with self._diagnostic_lock:
            self._tf_links = results

    def diagnostic_snapshot(self) -> dict[str, Any]:
        now = unix_time()
        with self._diagnostic_lock:
            heartbeat = self._executor_heartbeat
            topic_seen = dict(self._topic_seen)
            tf_links = {name: dict(value) for name, value in self._tf_links.items()}
            publications = {
                name: dict(value) for name, value in self._publications.items()
            }

        executor_age = max(0.0, now - heartbeat) if heartbeat else None
        executor_alive = bool(
            self.ready
            and self.thread is not None
            and self.thread.is_alive()
            and executor_age is not None
            and executor_age <= 3.0
        )
        topic_ages = {
            name: {
                "last_seen": stamp,
                "age_sec": round(max(0.0, now - stamp), 2),
            }
            for name, stamp in topic_seen.items()
        }

        processes = self.hub.state.get("processes", {})
        navigation_ready = bool(self.hub.state.get("navigation", {}).get("ready"))
        missing: list[str] = []
        stale: list[str] = []

        def process_active(name: str) -> bool:
            return processes.get(name, {}).get("active_state") == "active"

        if navigation_ready or process_active("nav"):
            if "map" not in topic_seen:
                missing.append("/map")
            tf_age = topic_ages.get("tf_pose", {}).get("age_sec")
            if tf_age is None or tf_age > 3.0:
                stale.append("TF map->base_footprint")
        for process_name, topic_name, label in (
            ("patrol", "patrol", "/patrol/status"),
            ("isa", "isa", "/isa/status"),
            ("evaluation", "evaluation", "/evaluation/status"),
        ):
            age = topic_ages.get(topic_name, {}).get("age_sec")
            if process_active(process_name) and age is None:
                missing.append(label)
            elif process_active(process_name) and age is not None and age > 5.0:
                stale.append(label)

        map_base = tf_links.get("map_base", {})
        if (
            not executor_alive
            and self.ready
            and self.thread is not None
            and self.thread.is_alive()
            and now - self._started_at < 4.0
        ):
            status = "starting"
            message = "Esperando primer heartbeat del executor"
        elif not executor_alive:
            status = "offline"
            message = "Executor ROS sin heartbeat"
        elif "TF map->base_footprint" in stale and not map_base.get("ok", False):
            status = "blocked"
            message = map_base.get("error") or "TF map->base_footprint no disponible"
        elif missing or stale:
            status = "partial"
            details = missing + stale
            message = "Sin datos: " + ", ".join(details)
        elif not topic_seen:
            status = "waiting"
            message = "Executor activo; esperando topicos"
        else:
            status = "ok"
            message = "Puente ROS recibiendo datos"

        return {
            "status": status,
            "message": message,
            "ready": self.ready,
            "executor_alive": executor_alive,
            "executor_age_sec": round(executor_age, 2) if executor_age is not None else None,
            "thread_alive": bool(self.thread and self.thread.is_alive()),
            "started_at": self._started_at,
            "topics": topic_ages,
            "tf": tf_links,
            "publications": publications,
            "missing": missing,
            "stale": stale,
            "updated_at": now,
        }

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
            from std_msgs.msg import Int32MultiArray, UInt16
            from std_srvs.srv import Trigger
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
            self.publishers["arm_cmd"] = self.node.create_publisher(
                String, "/arm/cmd", 10
            )
            self.publishers["arm_pose"] = self.node.create_publisher(
                String, "/arm/pose_cmd", 10
            )
            self.publishers["arm_joint"] = self.node.create_publisher(
                Int32MultiArray, "/arm/joint_cmd", 10
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
            self.publishers["evaluation"] = self.node.create_publisher(
                String, "/evaluation/command", 10
            )
            self.publishers["dashboard_video_status"] = self.node.create_publisher(
                String, "/dashboard/video_status_json", 10
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
                String, "/arm/joint_status", self._on_arm_joint_status, 10
            )
            self.node.create_subscription(
                String,
                "/ros_robot_controller/connection_status_json",
                self._on_arm_controller_status,
                10,
            )
            self.node.create_subscription(
                UInt16,
                "/ros_robot_controller/battery",
                self._on_battery,
                10,
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
            self.node.create_subscription(
                String,
                "/evaluation/status",
                self._on_evaluation_status,
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
            self.node.create_timer(1.0, self._heartbeat)
            self._arm_connection_client = self.node.create_client(
                Trigger, "/ros_robot_controller/connection_status"
            )
            self.node.create_timer(2.0, self._update_arm_health)

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
            self._record_publication(subsystem, command, False, "publisher no disponible")
            return False
        try:
            from std_msgs.msg import String

            self.publishers[subsystem].publish(String(data=command))
            self._record_publication(subsystem, command, True)
            return True
        except Exception as exc:
            self._record_publication(subsystem, command, False, str(exc))
            return False

    def publish_json_topic(self, subsystem: str, payload: dict[str, Any]) -> bool:
        if not self.ready or subsystem not in self.publishers:
            return False
        try:
            from std_msgs.msg import String

            self.publishers[subsystem].publish(
                String(data=json.dumps(payload, ensure_ascii=True))
            )
            return True
        except Exception:
            return False

    def publish_arm_command(self, command: str) -> bool:
        if command in ARM_POSE_CATALOG.get("poses", []):
            if self.subscriber_count("arm_pose") < 1:
                self._record_publication("arm_pose", command, False, "sin suscriptor")
                return False
            return self.publish("arm_pose", command)
        if command == "stop":
            if self.subscriber_count("arm_cmd") < 1:
                self._record_publication("arm_cmd", command, False, "sin suscriptor")
                return False
            return self.publish("arm_cmd", "stop")
        pulses = {"gripper_open": 0, "gripper_close": 580}
        if command not in pulses or not self.ready or "arm_joint" not in self.publishers:
            self._record_publication("arm_joint", command, False, "comando no disponible")
            return False
        if self.subscriber_count("arm_joint") < 1:
            self._record_publication("arm_joint", command, False, "sin suscriptor")
            return False
        try:
            from std_msgs.msg import Int32MultiArray

            self.publishers["arm_joint"].publish(
                Int32MultiArray(data=[6, pulses[command], 600])
            )
            self._record_publication("arm_joint", command, True)
            return True
        except Exception as exc:
            self._record_publication("arm_joint", command, False, str(exc))
            return False

    def subscriber_count(self, subsystem: str) -> int:
        publisher = self.publishers.get(subsystem)
        if not self.ready or publisher is None:
            return 0
        try:
            return int(publisher.get_subscription_count())
        except Exception:
            return 0

    def publish_initial_pose(
        self,
        x: float,
        y: float,
        yaw: float,
        frame_id: str = "map",
    ) -> bool:
        if not self.ready or "initialpose" not in self.publishers or self.node is None:
            self._record_publication(
                "initialpose",
                f"x={float(x):.3f} y={float(y):.3f} yaw={float(yaw):.3f}",
                False,
                "publisher no disponible",
            )
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
            self._record_publication(
                "initialpose",
                f"x={float(x):.3f} y={float(y):.3f} yaw={float(yaw):.3f}",
                True,
            )
            return True
        except Exception as exc:
            self._record_publication("initialpose", "pose estimate", False, str(exc))
            return False

    def _update_json(self, section: str, raw: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        self._touch_topic(section)
        payload["online"] = True
        payload["updated_at"] = unix_time()
        self.hub.from_thread(self.hub.update_section(section, payload))
        return payload

    def _on_patrol_status(self, msg: Any) -> None:
        self._touch_topic("patrol")
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

    def _on_arm_joint_status(self, msg: Any) -> None:
        try:
            payload = json.loads(msg.data)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        self._touch_topic("arm")
        self.hub.from_thread(
            self.hub.update_section(
                "arm",
                {
                    "last_command": "joint",
                    "last_joint": payload.get("joint"),
                    "last_pulse": payload.get("pulse"),
                    "updated_at": unix_time(),
                },
            )
        )

    def _on_battery(self, msg: Any) -> None:
        try:
            raw_mv = int(msg.data)
        except (TypeError, ValueError, AttributeError):
            return
        if raw_mv <= 0:
            return

        voltage = raw_mv / 1000.0
        alpha = max(0.01, min(1.0, BATTERY_EMA_ALPHA))
        if self._battery_voltage_ema is None:
            self._battery_voltage_ema = voltage
        else:
            self._battery_voltage_ema = (
                alpha * voltage + (1.0 - alpha) * self._battery_voltage_ema
            )
        filtered = self._battery_voltage_ema
        percent = battery_percent_from_voltage(filtered)
        self._touch_topic("battery")
        self.hub.from_thread(
            self.hub.update_section(
                "battery",
                {
                    "online": True,
                    "raw_mv": raw_mv,
                    "voltage_v": round(voltage, 3),
                    "filtered_voltage_v": round(filtered, 3),
                    "cell_voltage_v": round(filtered / BATTERY_CELL_COUNT, 3),
                    "percent": percent,
                    "updated_at": unix_time(),
                },
            )
        )

    def _on_arm_controller_status(self, msg: Any) -> None:
        try:
            payload = json.loads(msg.data)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        self._touch_topic("arm_controller")
        connected = bool(payload.get("connected"))
        device = str(payload.get("device") or "")
        error = str(payload.get("last_error") or "")
        message = (
            f"connected=True device={device or 'none'}"
            if connected
            else error or f"connected=False device={device or 'none'}"
        )
        arm = self.hub.state.get("arm", {})
        self.hub.from_thread(
            self.hub.update_section(
                "arm",
                {
                    "controller_service": True,
                    "controller_connected": connected,
                    "controller_message": message[:160],
                    "controller_status": payload,
                    "online": bool(
                        connected
                        and arm.get("core_online", False)
                        and arm.get("poses_online", False)
                    ),
                    "ready_reason": (
                        "Listo"
                        if connected and arm.get("core_online", False) and arm.get("poses_online", False)
                        else message[:160]
                    ),
                    "updated_at": unix_time(),
                },
            )
        )

    def _update_arm_health(self) -> None:
        if self.node is None:
            return
        try:
            node_names = set(self.node.get_node_names())
        except Exception:
            node_names = set()
        core_online = "emma_arm_core" in node_names
        poses_online = bool({"emma_pose_player", "emma_arm_poses"} & node_names)
        teleop_online = "emma_arm_teleop_keys" in node_names
        controller_service = bool(
            self._arm_connection_client
            and self._arm_connection_client.service_is_ready()
        )
        current = self.hub.state.get("arm", {})
        values = {
            "core_online": core_online,
            "poses_online": poses_online,
            "teleop_online": teleop_online,
            "controller_service": controller_service,
            "online": bool(
                core_online
                and poses_online
                and current.get("controller_connected", False)
            ),
            "ready_reason": (
                "Listo"
                if core_online and poses_online and current.get("controller_connected", False)
                else "Esperando emma_arm_core"
                if not core_online
                else "Esperando emma_pose_player"
                if not poses_online
                else current.get("controller_message") or "Esperando STM32"
            ),
            "pose_catalog": ARM_POSE_CATALOG,
            "updated_at": unix_time(),
        }
        self.hub.from_thread(self.hub.update_section("arm", values))

        if not controller_service:
            self.hub.from_thread(
                self.hub.update_section(
                    "arm",
                    {
                        "controller_connected": False,
                        "controller_message": "Servicio no disponible",
                        "ready_reason": "Servicio /ros_robot_controller/connection_status no disponible",
                        "online": False,
                        "updated_at": unix_time(),
                    },
                )
            )
            return
        if self._arm_connection_future is not None and not self._arm_connection_future.done():
            return
        try:
            from std_srvs.srv import Trigger

            self._arm_connection_future = self._arm_connection_client.call_async(
                Trigger.Request()
            )
            self._arm_connection_future.add_done_callback(self._on_arm_connection)
        except Exception as exc:
            self.hub.from_thread(
                self.hub.update_section(
                    "arm",
                    {
                        "controller_connected": False,
                        "controller_message": str(exc)[:160],
                        "ready_reason": str(exc)[:160],
                        "online": False,
                        "updated_at": unix_time(),
                    },
                )
            )

    def _on_arm_connection(self, future: Any) -> None:
        try:
            response = future.result()
            connected = bool(response.success)
            message = str(response.message)
        except Exception as exc:
            connected = False
            message = str(exc)
        arm = self.hub.state.get("arm", {})
        self.hub.from_thread(
            self.hub.update_section(
                "arm",
                {
                    "controller_connected": connected,
                    "controller_message": message[:160],
                    "ready_reason": (
                        "Listo"
                        if connected and arm.get("core_online", False) and arm.get("poses_online", False)
                        else message[:160] or "STM32 no confirmo conexion"
                    ),
                    "online": bool(
                        connected
                        and arm.get("core_online", False)
                        and arm.get("poses_online", False)
                    ),
                    "updated_at": unix_time(),
                },
            )
        )

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
        self._touch_topic(section)
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

    def _on_evaluation_status(self, msg: Any) -> None:
        payload = self._parse_json(msg.data)
        if payload is None:
            return
        self._touch_topic("evaluation")
        payload["collector_online"] = True
        payload["updated_at"] = unix_time()
        run_path = Path(str(payload.get("run_path", "")))
        metadata = read_json_file(run_path / "metadata.json") if run_path.is_dir() else {}
        for key in (
            "name",
            "trial_type",
            "trial_type_label",
            "operator",
            "location",
            "notes",
            "od_scene_mode",
            "od_expected_classes",
            "od_expected_cameras",
        ):
            if key in metadata:
                payload[key] = metadata[key]
        self.hub.from_thread(self.hub.update_section("evaluation", payload))

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _on_map(self, msg: Any) -> None:
        self._touch_topic("map")
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
        self._touch_topic("markers")
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

        self._probe_tf_links()

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
        self._touch_topic("tf_pose")
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


class EvaluationMonitor:
    def __init__(self, hub: DashboardHub) -> None:
        self.hub = hub

    async def refresh(self) -> dict[str, Any]:
        values = evaluation_active_state()
        process = await service_manager.status("evaluation")
        values.update(
            {
                "collector_online": process["active_state"] == "active",
                "clock_synchronized": time.time() > 1_600_000_000,
                "updated_at": unix_time(),
            }
        )
        live = self.hub.state.get("evaluation", {})
        if values["active"] and values["run_id"] == live.get("run_id"):
            for key in ("interventions", "seen_topics", "tf_outages", "last_report"):
                if key in live:
                    values[key] = live[key]
        await self.hub.update_section("evaluation", values)
        return values

    async def monitor(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(2.0)


evaluation_monitor = EvaluationMonitor(hub)


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


def parse_tegrastats_line(line: str) -> dict[str, Any] | None:
    ram_match = re.search(r"\bRAM\s+(\d+)/(\d+)MB", line)
    cpu_match = re.search(r"\bCPU\s+\[([^\]]+)\]", line)
    gpu_match = re.search(r"\bGR3D_FREQ\s+(\d+)%", line)

    if not ram_match:
        return None

    cpu_values: list[int] = []
    if cpu_match:
        for token in cpu_match.group(1).split(","):
            match = re.search(r"(\d+)%@", token)
            if match:
                cpu_values.append(int(match.group(1)))

    swap_match = re.search(r"\bSWAP\s+(\d+)/(\d+)MB", line)
    temps = {
        name: float(value)
        for name, value in re.findall(r"\b([A-Za-z0-9_]+)@([0-9.]+)C", line)
    }
    power_match = re.search(r"\bVDD_IN\s+(\d+)mW(?:/(\d+)mW)?", line)

    ram_used = int(ram_match.group(1))
    ram_total = int(ram_match.group(2))
    ram_percent = round((ram_used / ram_total) * 100.0, 1) if ram_total else None
    temp_max = max(temps.values()) if temps else None

    status = "ok"
    if (
        (ram_percent is not None and ram_percent >= 90)
        or (temp_max is not None and temp_max >= 78)
    ):
        status = "critical"
    elif (
        (ram_percent is not None and ram_percent >= 80)
        or (temp_max is not None and temp_max >= 70)
    ):
        status = "warn"

    return {
        "online": True,
        "source": "tegrastats",
        "raw": line.strip(),
        "status": status,
        "ram_used_mb": ram_used,
        "ram_total_mb": ram_total,
        "ram_percent": ram_percent,
        "swap_used_mb": int(swap_match.group(1)) if swap_match else None,
        "swap_total_mb": int(swap_match.group(2)) if swap_match else None,
        "cpu_percent": round(sum(cpu_values) / len(cpu_values), 1)
        if cpu_values
        else None,
        "cpu_cores": cpu_values,
        "gpu_percent": int(gpu_match.group(1)) if gpu_match else None,
        "temp_c": round(temp_max, 1) if temp_max is not None else None,
        "temps": temps,
        "power_w": round(int(power_match.group(1)) / 1000.0, 2)
        if power_match
        else None,
        "power_avg_w": round(
            int(power_match.group(2) or power_match.group(1)) / 1000.0,
            2,
        )
        if power_match
        else None,
        "updated_at": unix_time(),
    }


class OrinHealthMonitor:
    def __init__(self, hub: DashboardHub) -> None:
        self.hub = hub
        self._previous_online: bool | None = None

    async def _set_offline(self, reason: str) -> None:
        await self.hub.update_section(
            "orin_health",
            {
                "online": False,
                "source": "tegrastats",
                "error": reason,
                "updated_at": unix_time(),
            },
        )
        if self._previous_online is not False:
            await self.hub.add_event("orin", f"tegrastats offline: {reason}", "warn")
        self._previous_online = False

    async def monitor(self) -> None:
        if not TEGRASTATS_BIN.exists():
            await self._set_offline(f"{TEGRASTATS_BIN} no existe")
            while True:
                await asyncio.sleep(30.0)

        while True:
            process: asyncio.subprocess.Process | None = None
            try:
                process = await asyncio.create_subprocess_exec(
                    str(TEGRASTATS_BIN),
                    "--interval",
                    "1000",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                if self._previous_online is False:
                    await self.hub.add_event("orin", "tegrastats online", "ok")

                assert process.stdout is not None
                while True:
                    raw_line = await process.stdout.readline()
                    if not raw_line:
                        break
                    payload = parse_tegrastats_line(
                        raw_line.decode(errors="replace").strip()
                    )
                    if payload is None:
                        continue
                    await self.hub.update_section("orin_health", payload)
                    self._previous_online = True

                stderr = ""
                if process.stderr is not None:
                    stderr = (await process.stderr.read()).decode(errors="replace")
                await self._set_offline(stderr.strip() or "proceso detenido")
            except asyncio.CancelledError:
                if process is not None and process.returncode is None:
                    process.terminate()
                    with suppress(ProcessLookupError, asyncio.TimeoutError):
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                raise
            except Exception as exc:
                await self._set_offline(str(exc))
            finally:
                if process is not None and process.returncode is None:
                    process.terminate()
                    with suppress(ProcessLookupError, asyncio.TimeoutError):
                        await asyncio.wait_for(process.wait(), timeout=2.0)

            await asyncio.sleep(3.0)


orin_health_monitor = OrinHealthMonitor(hub)


async def monitor_connections() -> None:
    # This backend runs on the Orin itself. Probing its old Wi-Fi address made
    # the dashboard report the Orin offline whenever NetworkManager switched
    # the same radio to AP mode (10.42.0.1).
    while True:
        await hub.update_section(
            "connections", {"orin": True, "updated_at": unix_time()}
        )
        await asyncio.sleep(5.0)


def read_network_interfaces() -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            ["ip", "-j", "-4", "address", "show", "up"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode != 0:
            return []
        interfaces: list[dict[str, str]] = []
        for item in json.loads(result.stdout or "[]"):
            name = str(item.get("ifname", ""))
            if not name or name == "lo":
                continue
            for address in item.get("addr_info", []):
                if address.get("family") != "inet":
                    continue
                interfaces.append(
                    {
                        "name": name,
                        "address": str(address.get("local", "")),
                        "prefix": str(address.get("prefixlen", "")),
                    }
                )
        return interfaces
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return []


def append_ros_diagnostic(payload: dict[str, Any]) -> None:
    try:
        ROS_DIAGNOSTICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ROS_DIAGNOSTICS_LOG.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    except OSError:
        pass


async def monitor_ros_diagnostics() -> None:
    previous_signature: tuple[Any, ...] | None = None
    network: list[dict[str, str]] = []
    network_checked = 0.0
    while True:
        now = unix_time()
        if now - network_checked >= 5.0:
            network = await asyncio.to_thread(read_network_interfaces)
            network_checked = now

        payload = ros_bridge.diagnostic_snapshot()
        payload["network"] = network
        payload["log_path"] = str(ROS_DIAGNOSTICS_LOG)
        await hub.update_section("ros_diagnostics", payload)
        await hub.update_section(
            "connections",
            {
                "ros": bool(payload.get("executor_alive")),
                "updated_at": now,
            },
        )

        tf_signature = tuple(
            (name, bool(value.get("ok")), str(value.get("error", "")))
            for name, value in sorted(payload.get("tf", {}).items())
        )
        network_signature = tuple(
            (item.get("name"), item.get("address")) for item in network
        )
        signature = (
            payload.get("status"),
            payload.get("message"),
            tuple(payload.get("missing", [])),
            tuple(payload.get("stale", [])),
            tf_signature,
            network_signature,
        )
        if signature != previous_signature:
            record = dict(payload)
            record["recorded_at"] = now
            await asyncio.to_thread(append_ros_diagnostic, record)
            if previous_signature is not None:
                status = str(payload.get("status", "offline"))
                level = "error" if status in {"blocked", "offline"} else "warn" if status == "partial" else "ok"
                await hub.add_event(
                    "dashboard",
                    f"ROS bridge {status.upper()}: {payload.get('message', '')}",
                    level,
                )
            previous_signature = signature

        await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(_: FastAPI):
    hub.bind_loop(asyncio.get_running_loop())
    ros_bridge.start()
    monitor_task = asyncio.create_task(monitor_connections())
    service_task = asyncio.create_task(service_manager.monitor())
    vision_task = asyncio.create_task(vision_monitor.monitor())
    health_task = asyncio.create_task(orin_health_monitor.monitor())
    evaluation_task = asyncio.create_task(evaluation_monitor.monitor())
    ros_diagnostic_task = asyncio.create_task(monitor_ros_diagnostics())
    try:
        yield
    finally:
        monitor_task.cancel()
        service_task.cancel()
        vision_task.cancel()
        health_task.cancel()
        evaluation_task.cancel()
        ros_diagnostic_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        with suppress(asyncio.CancelledError):
            await service_task
        with suppress(asyncio.CancelledError):
            await vision_task
        with suppress(asyncio.CancelledError):
            await health_task
        with suppress(asyncio.CancelledError):
            await evaluation_task
        with suppress(asyncio.CancelledError):
            await ros_diagnostic_task
        ros_bridge.stop()


app = FastAPI(title="EMMA Dashboard", version="1.14.0", lifespan=lifespan)
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


class EvaluationStartBody(BaseModel):
    trial_type: str
    name: str = ""
    operator: str = "dashboard"
    location: str = "casa"
    notes: str = ""
    scene_mode: str = "free"
    expected_classes: list[str] = Field(default_factory=list)
    cameras: list[str] = Field(default_factory=list)


class EvaluationTextBody(BaseModel):
    text: str


class VideoReceiverStatusBody(BaseModel):
    receiver: str = "dashboard"
    cameras: dict[str, dict[str, Any]] = Field(default_factory=dict)


async def ensure_evaluation_collector() -> dict[str, Any]:
    if not EVALUATION_SCRIPT.is_file():
        raise RuntimeError(f"No existe el recolector C26: {EVALUATION_SCRIPT}")
    status = await service_manager.status("evaluation")
    if status["load_state"] == "not-found":
        raise RuntimeError("emma-evaluation.service no esta instalado")
    if status["active_state"] != "active":
        await service_manager.action("evaluation", "start")

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if ros_bridge.subscriber_count("evaluation") > 0:
            return await service_manager.status("evaluation")
        await asyncio.sleep(0.2)
    raise RuntimeError("El recolector Evaluation no aparecio en ROS 2")


async def publish_evaluation_command(payload: dict[str, Any]) -> None:
    if not ros_bridge.publish("evaluation", json.dumps(payload, ensure_ascii=True)):
        raise RuntimeError("No se pudo publicar /evaluation/command")


def evaluation_warnings(trial_type: str, cameras: list[str]) -> list[str]:
    processes = hub.state.get("processes", {})
    active = {
        name
        for name, status in processes.items()
        if status.get("active_state") == "active"
    }
    required: list[tuple[str, str]] = []
    if trial_type == "nav_slam":
        required = [("nav", "Nav2"), ("patrol", "Patrol")]
    elif trial_type == "od_live":
        if "astra" in cameras:
            required.append(("od_astra", "OD Astra"))
        if "arm_cam" in cameras:
            required.append(("od_arm", "OD Arm Cam"))
    elif trial_type == "video_stream":
        required = [("video", "Video WebRTC")]
    elif trial_type == "isa_mission":
        required = [("isa", "ISA")]
    return [f"{label} no esta activo" for name, label in required if name not in active]


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


@app.get("/api/evaluation")
async def evaluation_status() -> dict[str, Any]:
    state = await evaluation_monitor.refresh()
    return {
        "ok": True,
        "evaluation": state,
        "types": EVALUATION_TYPES,
        "reports": evaluation_reports(),
    }



def _dashboard_receiver_camera_payload(camera: str, client_status: dict[str, Any]) -> dict[str, Any]:
    camera_key = "od_arm" if camera == "arm_cam" else "od_astra"
    od_state = hub.state.get(camera_key, {}) if isinstance(hub.state, dict) else {}
    vision_state = hub.state.get("vision", {}) if isinstance(hub.state, dict) else {}
    ready_key = "arm_stream_ready" if camera == "arm_cam" else "astra_stream_ready"
    connected_key = "arm_camera_connected" if camera == "arm_cam" else "astra_camera_connected"
    now = unix_time()
    try:
        updated_at = float(od_state.get("updated_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        updated_at = 0.0
    stream_fresh = updated_at > 0.0 and now - updated_at < 4.0
    iframe_loaded = bool(client_status.get("iframe_loaded", False))
    visible = bool(client_status.get("visible", False))
    active = bool(vision_state.get(ready_key, False)) and iframe_loaded and visible

    return {
        "camera": camera,
        "active": active,
        "visible": visible,
        "iframe_loaded": iframe_loaded,
        "stream_ready": bool(vision_state.get(ready_key, False)),
        "camera_connected": bool(vision_state.get(connected_key, False)),
        "last_frame_age_ms": round(max(0.0, now - updated_at) * 1000.0, 3) if updated_at else None,
        "fps": od_state.get("annotated_fps"),
        "jitter_ms": od_state.get("frame_jitter_ms"),
        "latency_ms": od_state.get("processing_latency_max_ms", od_state.get("processing_latency_ms")),
        "packet_loss_percent": od_state.get("frame_read_failure_percent", 0.0),
        "source_fresh": stream_fresh,
        "updated_at": now,
    }


@app.post("/api/video/receiver-status")
async def video_receiver_status(body: VideoReceiverStatusBody) -> dict[str, Any]:
    now = unix_time()
    requested = body.cameras or {}
    cameras: dict[str, dict[str, Any]] = {}
    for raw_name, status in requested.items():
        name = str(raw_name).strip().lower()
        if name == "arm":
            name = "arm_cam"
        if name not in {"astra", "arm_cam"} or not isinstance(status, dict):
            continue
        cameras[name] = _dashboard_receiver_camera_payload(name, status)

    payload = {
        "schema_version": 1,
        "receiver": body.receiver.strip()[:40] or "dashboard",
        "source": "dashboard",
        "timestamp": now,
        "cameras": cameras,
    }
    published = ros_bridge.publish_json_topic("dashboard_video_status", payload)
    await hub.update_section(
        "dashboard_video",
        {"online": True, "updated_at": now, "published": published, "cameras": cameras},
    )
    return {"ok": True, "published": published, "status": payload}


@app.get("/api/evaluation/reports/{run_id}")
async def evaluation_report(run_id: str) -> dict[str, Any]:
    requested = run_id.strip()
    if not requested or Path(requested).name != requested:
        raise HTTPException(status_code=400, detail="Ensayo no permitido")
    run_path = EVALUATION_ROOT / "runs" / requested
    metadata = read_json_file(run_path / "metadata.json")
    report = read_json_file(run_path / "report.json")
    if not metadata and not report:
        raise HTTPException(status_code=404, detail="Ensayo no encontrado")
    return {"ok": True, "metadata": metadata, "report": report}


@app.post("/api/evaluation/start")
async def evaluation_start(body: EvaluationStartBody) -> dict[str, Any]:
    trial_type = body.trial_type.strip().lower()
    if trial_type not in EVALUATION_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de ensayo no permitido")
    if evaluation_active_state()["active"]:
        raise HTTPException(status_code=409, detail="Ya existe un ensayo activo")
    if time.time() <= 1_600_000_000:
        raise HTTPException(status_code=409, detail="Reloj del Orin no sincronizado")

    location = body.location.strip()[:48] or "casa"
    operator = body.operator.strip()[:48] or "dashboard"
    name = body.name.strip()[:64] or automatic_evaluation_name(location, trial_type)
    scene_mode = body.scene_mode.strip().lower()
    expected_classes = list(dict.fromkeys(
        value.strip().lower() for value in body.expected_classes if value.strip()
    ))
    cameras = list(dict.fromkeys(
        value.strip().lower() for value in body.cameras if value.strip()
    ))

    if trial_type == "od_live":
        if scene_mode not in {"isolated", "mixed", "free"}:
            raise HTTPException(status_code=400, detail="Escena OD no permitida")
        invalid_classes = sorted(set(expected_classes) - EVALUATION_CLASSES)
        invalid_cameras = sorted(set(cameras) - EVALUATION_CAMERAS)
        if invalid_classes or invalid_cameras:
            raise HTTPException(status_code=400, detail="Configuracion OD no permitida")
        if not cameras:
            raise HTTPException(status_code=400, detail="Selecciona al menos una camara")
        if scene_mode in {"isolated", "mixed"} and not expected_classes:
            raise HTTPException(status_code=400, detail="Selecciona las clases esperadas")
        if scene_mode == "isolated" and len(expected_classes) != 1:
            raise HTTPException(status_code=400, detail="Escena aislada requiere una clase")
        if scene_mode == "free":
            expected_classes = []
    else:
        scene_mode = ""
        expected_classes = []
        cameras = []

    try:
        await ensure_evaluation_collector()
        await publish_evaluation_command(
            {
                "action": "start",
                "metadata": {
                    "name": name,
                    "trial_type": trial_type,
                    "trial_type_label": EVALUATION_TYPES[trial_type]["label"],
                    "operator": operator,
                    "location": location,
                    "platform": "orin",
                    "notes": body.notes.strip()[:500],
                    "od_scene_mode": scene_mode,
                    "od_expected_classes": expected_classes,
                    "od_expected_cameras": cameras,
                    "allow_unsynchronized_clock": False,
                },
            }
        )
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            state = evaluation_active_state()
            if state["active"]:
                state = await evaluation_monitor.refresh()
                warnings = evaluation_warnings(trial_type, cameras)
                await hub.add_event("evaluation", f"Ensayo iniciado: {name}", "command")
                return {"ok": True, "evaluation": state, "warnings": warnings}
            await asyncio.sleep(0.15)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise HTTPException(status_code=503, detail="El recolector no confirmo el inicio")


@app.post("/api/evaluation/stop")
async def evaluation_stop() -> dict[str, Any]:
    active = evaluation_active_state()
    if not active["active"]:
        raise HTTPException(status_code=409, detail="No hay un ensayo activo")
    try:
        await ensure_evaluation_collector()
        await publish_evaluation_command({"action": "stop"})
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if not evaluation_active_state()["active"]:
                await service_manager.action("evaluation", "stop")
                state = await evaluation_monitor.refresh()
                reports = evaluation_reports()
                await hub.add_event(
                    "evaluation",
                    f"Ensayo finalizado: {active['run_id']}",
                    "ok",
                )
                return {"ok": True, "evaluation": state, "reports": reports}
            await asyncio.sleep(0.25)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise HTTPException(status_code=503, detail="El reporte no termino dentro del tiempo esperado")


@app.post("/api/evaluation/note")
async def evaluation_note(body: EvaluationTextBody) -> dict[str, Any]:
    note = body.text.strip()[:500]
    if not note:
        raise HTTPException(status_code=400, detail="Escribe una nota")
    if not evaluation_active_state()["active"]:
        raise HTTPException(status_code=409, detail="No hay un ensayo activo")
    try:
        await ensure_evaluation_collector()
        await publish_evaluation_command({"action": "note", "text": note})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await hub.add_event("evaluation", f"Nota: {note}", "info")
    return {"ok": True}


@app.post("/api/evaluation/intervention")
async def evaluation_intervention(body: EvaluationTextBody) -> dict[str, Any]:
    reason = body.text.strip()[:500]
    if not reason:
        raise HTTPException(status_code=400, detail="Describe la intervencion")
    if not evaluation_active_state()["active"]:
        raise HTTPException(status_code=409, detail="No hay un ensayo activo")
    try:
        await ensure_evaluation_collector()
        await publish_evaluation_command({"action": "intervention", "reason": reason})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await hub.add_event("evaluation", f"Intervencion: {reason}", "warn")
    return {"ok": True}


@app.post("/api/command")
async def command(body: CommandBody) -> dict[str, Any]:
    subsystem = body.subsystem.strip().lower()
    requested = body.command.strip().lower()
    if subsystem == "patrol":
        allowed = requested in PATROL_COMMANDS or requested in available_routes()
    elif subsystem == "isa":
        allowed = requested in ISA_COMMANDS
    elif subsystem == "arm":
        allowed = requested in ARM_DIRECT_COMMANDS or requested in ARM_POSE_CATALOG.get("poses", [])
    else:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=400, detail="Comando no permitido")
    if subsystem == "arm":
        arm_process = await service_manager.status("arm")
        if arm_process["active_state"] != "active":
            raise HTTPException(status_code=409, detail="El servicio del brazo no esta activo")
        arm_state = hub.state.get("arm", {})
        if not arm_state.get("controller_connected"):
            detail = arm_state.get("controller_message") or "STM32 no conectado"
            raise HTTPException(status_code=409, detail=f"Controller del brazo no listo: {detail}")
        if requested not in {"stop"} and not arm_state.get("poses_online"):
            raise HTTPException(status_code=409, detail="emma_pose_player no esta listo")
    published = (
        ros_bridge.publish_arm_command(requested)
        if subsystem == "arm"
        else ros_bridge.publish(subsystem, requested)
    )
    if not published:
        detail = (
            "Los nodos ROS del brazo no estan listos"
            if subsystem == "arm"
            else "Puente ROS 2 no disponible"
        )
        raise HTTPException(status_code=503, detail=detail)
    if subsystem == "arm":
        await hub.update_section(
            "arm",
            {"last_command": requested, "updated_at": unix_time()},
        )
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


@app.get("/api/arm/status")
async def arm_status() -> dict[str, Any]:
    return {
        "ok": True,
        "arm": hub.state.get("arm", {}),
        "pose_catalog": ARM_POSE_CATALOG,
        "process": await service_manager.status("arm"),
    }


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


@app.post("/api/dashboard/shutdown")
async def dashboard_shutdown() -> dict[str, Any]:
    await hub.add_event("dashboard", "Apagado solicitado desde la interfaz", "command")
    unit_name = f"emma-dashboard-stop-{int(time.monotonic() * 1000)}"
    code, stdout, stderr = await service_manager._run(
        "systemd-run",
        "--user",
        "--quiet",
        "--collect",
        f"--unit={unit_name}",
        "--on-active=1s",
        "/usr/bin/systemctl",
        "--user",
        "stop",
        "emma-dashboard.service",
        timeout=5.0,
    )
    if code != 0:
        detail = stderr or stdout or "No se pudo programar el apagado"
        raise HTTPException(status_code=503, detail=detail)
    return {"ok": True, "scheduled": True}


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
