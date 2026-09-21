from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import paramiko
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


PROJECT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_DIR / "emma_dashboard" / "static"
NODE_MODULES_DIR = PROJECT_DIR / "node_modules"

ORIN_HOST = os.environ.get("EMMA_ORIN_HOST", "192.168.68.72")
ORIN_USER = os.environ.get("EMMA_ORIN_USER", "jetson")
ORIN_KEY = Path(
    os.environ.get("EMMA_ORIN_KEY", "/home/adjor/.ssh/orion")
).expanduser()

PATROL_COMMANDS = {
    "start",
    "resume",
    "stop",
    "hold",
    "reload",
    "route_1",
    "route_2",
    "route_3",
    "speed_slow_linear",
    "speed_normal_linear",
    "speed_fast_linear",
    "speed_slow_omni",
    "speed_normal_omni",
    "speed_fast_omni",
}
ISA_COMMANDS = {"auto", "next", "reset"}


def unix_time() -> float:
    return round(time.time(), 3)


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
            from std_msgs.msg import String

            if not rclpy.ok():
                rclpy.init(args=None)

            self.node = rclpy.create_node("emma_dashboard")
            self.publishers["patrol"] = self.node.create_publisher(
                String, "/patrol/cmd", 10
            )
            self.publishers["isa"] = self.node.create_publisher(
                String, "/isa/cmd", 10
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

            self.executor = MultiThreadedExecutor(num_threads=2)
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
        self._update_json("patrol", msg.data)

    def _on_isa_json(self, msg: Any) -> None:
        self._update_json("isa", msg.data)

    def _on_base_json(self, msg: Any) -> None:
        self._update_json("base", msg.data)

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
    try:
        yield
    finally:
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        ros_bridge.stop()


app = FastAPI(title="EMMA Dashboard", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount(
    "/vendor",
    StaticFiles(directory=NODE_MODULES_DIR, check_dir=False),
    name="vendor",
)


class CommandBody(BaseModel):
    subsystem: str
    command: str


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return hub.snapshot()


@app.post("/api/command")
async def command(body: CommandBody) -> dict[str, Any]:
    subsystem = body.subsystem.strip().lower()
    requested = body.command.strip().lower()
    allowed = PATROL_COMMANDS if subsystem == "patrol" else ISA_COMMANDS
    if subsystem not in {"patrol", "isa"} or requested not in allowed:
        raise HTTPException(status_code=400, detail="Comando no permitido")
    if not ros_bridge.publish(subsystem, requested):
        raise HTTPException(status_code=503, detail="Puente ROS 2 no disponible")
    await hub.add_event(subsystem, f"CMD -> {requested}", "command")
    return {"ok": True, "subsystem": subsystem, "command": requested}


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


def open_ssh_terminal(cols: int, rows: int) -> tuple[paramiko.SSHClient, Any]:
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        hostname=ORIN_HOST,
        username=ORIN_USER,
        key_filename=str(ORIN_KEY),
        look_for_keys=False,
        allow_agent=False,
        timeout=6.0,
        banner_timeout=6.0,
        auth_timeout=6.0,
    )
    channel = client.invoke_shell(
        term="xterm-256color",
        width=max(20, cols),
        height=max(8, rows),
    )
    channel.settimeout(0.25)
    return client, channel


async def pump_terminal_output(websocket: WebSocket, channel: Any) -> None:
    await websocket.send_json({"type": "status", "value": "connected"})
    while not channel.closed:
        try:
            data = await asyncio.to_thread(channel.recv, 8192)
        except socket.timeout:
            await asyncio.sleep(0.01)
            continue
        if not data:
            break
        await websocket.send_bytes(data)


@app.websocket("/ws/terminal")
async def terminal_socket(websocket: WebSocket) -> None:
    if not local_websocket_origin(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    client: paramiko.SSHClient | None = None
    channel: Any = None
    output_task: asyncio.Task[Any] | None = None
    try:
        await websocket.send_json({"type": "status", "value": "connecting"})
        client, channel = await asyncio.to_thread(open_ssh_terminal, 120, 32)
        output_task = asyncio.create_task(pump_terminal_output(websocket, channel))

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message_type = message.get("type")
            if message_type == "input":
                channel.send(str(message.get("data", "")))
            elif message_type == "resize":
                cols = max(20, int(message.get("cols", 120)))
                rows = max(8, int(message.get("rows", 32)))
                channel.resize_pty(width=cols, height=rows)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        with suppress(Exception):
            await websocket.send_json(
                {"type": "status", "value": "error", "message": str(exc)}
            )
    finally:
        if output_task is not None:
            output_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await output_task
        if channel is not None:
            with suppress(Exception):
                channel.close()
        if client is not None:
            with suppress(Exception):
                client.close()
