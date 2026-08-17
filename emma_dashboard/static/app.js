const dashboardState = {
  connections: {},
  patrol: {},
  isa: {},
  base: {},
};

let events = [];
let activeFilter = "all";
let stateSocket = null;
let terminal = null;
let fitAddon = null;
let terminalSocket = null;
let terminalStarted = false;
let confirmResolver = null;

const byId = (id) => document.getElementById(id);

function text(id, value, fallback = "--") {
  const target = byId(id);
  if (!target) return;
  const normalized = value === null || value === undefined || value === "" ? fallback : value;
  target.textContent = String(normalized);
  target.title = String(normalized);
}

function setStateBadge(id, online, onlineLabel, offlineLabel, warning = false) {
  const badge = byId(id);
  if (!badge) return;
  badge.dataset.state = online ? "online" : warning ? "warn" : "offline";
  const dot = badge.querySelector(".status-dot") || document.createElement("span");
  dot.className = "status-dot";
  badge.replaceChildren(dot, document.createTextNode(online ? onlineLabel : offlineLabel));
}

function isFresh(section, seconds = 4) {
  if (!section || !section.updated_at) return false;
  return Date.now() / 1000 - Number(section.updated_at) < seconds;
}

function boolLabel(value, yes = "SI", no = "NO") {
  return value ? yes : no;
}

function fixed(value, digits, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(digits)}${suffix}`;
}

function syncSelect(id, value) {
  const select = byId(id);
  if (!select || !value) return;
  if ([...select.options].some((option) => option.value === value)) {
    select.value = value;
  }
}

function renderState() {
  const connections = dashboardState.connections || {};
  const patrol = dashboardState.patrol || {};
  const isa = dashboardState.isa || {};
  const base = dashboardState.base || {};

  const orinOnline = Boolean(connections.orin);
  const rosOnline = Boolean(connections.ros);
  const patrolOnline = Boolean(patrol.online) && isFresh(patrol);
  const isaOnline = Boolean(isa.online) && isFresh(isa);

  setStateBadge("orin-pill", orinOnline, "ORIN", "ORIN");
  setStateBadge("ros-pill", rosOnline, "ROS 2", "ROS 2");
  setStateBadge("patrol-online", patrolOnline, "ONLINE", "OFFLINE");
  setStateBadge("isa-online", isaOnline, "ONLINE", "OFFLINE");

  text("rail-orin", orinOnline ? "ONLINE" : "OFFLINE");
  text("rail-ros", rosOnline ? "ONLINE" : "OFFLINE");
  text("rail-nav2", patrolOnline ? (patrol.nav_ready ? "READY" : "WAITING") : "SIN DATOS");
  text("rail-owner", base.owner || patrol.base_control_owner);

  text("patrol-status", patrolOnline ? patrol.status : "sin datos");
  text("patrol-route", patrol.route);
  const pointIndex = Number(patrol.waypoint_index);
  const pointCount = Number(patrol.waypoint_count || 0);
  text(
    "patrol-waypoint",
    pointIndex >= 0 ? `${pointIndex + 1} / ${pointCount}` : pointCount ? `0 / ${pointCount}` : "--"
  );
  text("patrol-speed", patrol.speed);
  text(
    "patrol-odom",
    patrol.have_odom
      ? `x ${fixed(patrol.robot_x, 2)}  y ${fixed(patrol.robot_y, 2)}`
      : "sin odom"
  );
  text("patrol-owner", patrol.base_control_owner || base.owner);

  text("isa-state", isaOnline ? isa.state : "sin datos");
  text("isa-mode", isa.mode);
  text("isa-target", isa.target);
  text("isa-distance", fixed(isa.distance, 2, " m"));
  text("isa-offset", fixed(isa.offset, 3));
  text("isa-bin", isa.bin_active ? "ACTIVO" : "INACTIVO");
  text("isa-ready", isaOnline ? boolLabel(isa.target_ready) : "--");
  text("isa-patrol", isa.patrol_status);

  text("base-state", `${base.owner || "--"} / ${base.state || "sin datos"}`);
  text(
    "base-estop",
    base.updated_at ? `E-STOP ${boolLabel(base.estop, "ACTIVO", "OK")}` : "E-STOP --"
  );
  syncSelect("route-select", patrol.route);
  syncSelect("speed-select", patrol.speed);
  text("terminal-host", connections.orin_host || "192.168.68.72");
}

function formatEventTime(timestamp) {
  if (!timestamp) return "--:--:--";
  return new Date(Number(timestamp) * 1000).toLocaleTimeString("es-VE", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function eventMatches(event) {
  if (activeFilter === "all") return true;
  if (activeFilter === "error") return event.level === "warn" || event.level === "error";
  return event.source === activeFilter;
}

function buildEventRow(event) {
  const row = document.createElement("div");
  row.className = "event-row";
  row.dataset.level = event.level || "info";

  const time = document.createElement("span");
  time.className = "event-time";
  time.textContent = formatEventTime(event.time);

  const source = document.createElement("span");
  source.className = "event-source";
  source.textContent = event.source || "system";

  const message = document.createElement("span");
  message.className = "event-message";
  message.textContent = event.message || "";

  row.append(time, source, message);
  return row;
}

function renderEventList(container, sourceEvents, emptyLabel) {
  container.replaceChildren();
  if (!sourceEvents.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = emptyLabel;
    container.append(empty);
    return;
  }
  const fragment = document.createDocumentFragment();
  sourceEvents.forEach((event) => fragment.append(buildEventRow(event)));
  container.append(fragment);
}

function renderEvents() {
  renderEventList(byId("event-preview-list"), events.slice(0, 5), "Sin eventos recientes");
  renderEventList(
    byId("event-full-list"),
    events.filter(eventMatches),
    "Sin eventos para este filtro"
  );
}

function connectStateSocket() {
  if (stateSocket && stateSocket.readyState <= WebSocket.OPEN) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  stateSocket = new WebSocket(`${protocol}://${location.host}/ws/state`);

  stateSocket.onmessage = (message) => {
    const payload = JSON.parse(message.data);
    if (payload.type === "snapshot") {
      Object.assign(dashboardState, payload.state || {});
      events = payload.events || [];
      renderState();
      renderEvents();
      return;
    }
    if (payload.type === "state") {
      dashboardState[payload.section] = payload.value || {};
      renderState();
      return;
    }
    if (payload.type === "event") {
      events.unshift(payload.event);
      events = events.slice(0, 250);
      renderEvents();
    }
  };

  stateSocket.onclose = () => {
    dashboardState.connections = {...dashboardState.connections, ros: false};
    renderState();
    window.setTimeout(connectStateSocket, 1800);
  };
}

function toast(message, type = "info") {
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.textContent = message;
  byId("toast-stack").append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function confirmAction(message) {
  const modal = byId("confirm-modal");
  text("confirm-message", message, "Confirmar comando?");
  modal.hidden = false;
  byId("confirm-accept").focus();
  return new Promise((resolve) => {
    confirmResolver = resolve;
  });
}

function closeConfirm(result) {
  byId("confirm-modal").hidden = true;
  if (confirmResolver) confirmResolver(result);
  confirmResolver = null;
}

async function sendCommand(subsystem, command, confirmation = "") {
  if (confirmation && !(await confirmAction(confirmation))) return;
  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({subsystem, command}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo enviar el comando");
    toast(`${subsystem.toUpperCase()}: ${command}`);
  } catch (error) {
    toast(error.message || "Error enviando comando", "error");
  }
}

function switchView(viewName) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === `view-${viewName}`);
  });
  document.querySelectorAll(".tab-button").forEach((button) => {
    const active = button.dataset.viewTarget === viewName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  window.history.replaceState(null, "", `#${viewName}`);
  if (viewName === "terminal") startTerminal();
}

function updateTerminalBadge(state, message = "") {
  const labels = {
    connected: "CONECTADA",
    connecting: "CONECTANDO",
    error: "ERROR",
    offline: "DESCONECTADA",
  };
  setStateBadge(
    "terminal-status",
    state === "connected",
    labels.connected,
    labels[state] || labels.offline,
    state === "connecting"
  );
  if (message) toast(`Terminal: ${message}`, "error");
}

function connectTerminal() {
  if (!terminal) return;
  if (terminalSocket) terminalSocket.close();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  terminalSocket = new WebSocket(`${protocol}://${location.host}/ws/terminal`);
  terminalSocket.binaryType = "arraybuffer";
  updateTerminalBadge("connecting");

  terminalSocket.onopen = () => {
    terminalSocket.send(JSON.stringify({type: "resize", cols: terminal.cols, rows: terminal.rows}));
  };

  terminalSocket.onmessage = (message) => {
    if (typeof message.data === "string") {
      const payload = JSON.parse(message.data);
      if (payload.type === "status") {
        updateTerminalBadge(payload.value, payload.message || "");
      }
      return;
    }
    terminal.write(new Uint8Array(message.data));
  };

  terminalSocket.onclose = () => updateTerminalBadge("offline");
  terminalSocket.onerror = () => updateTerminalBadge("error", "fallo de conexion SSH");
}

function startTerminal() {
  if (!terminalStarted) {
    terminalStarted = true;
    terminal = new Terminal({
      cursorBlink: true,
      cursorStyle: "bar",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      fontSize: 14,
      letterSpacing: 0,
      lineHeight: 1.16,
      scrollback: 10000,
      allowTransparency: false,
      theme: {
        background: "#07090a",
        foreground: "#dce3e7",
        cursor: "#22d3ee",
        cursorAccent: "#07090a",
        selectionBackground: "#244d56",
        black: "#111417",
        red: "#ff5964",
        green: "#3fe38b",
        yellow: "#f4b942",
        blue: "#5b8cff",
        magenta: "#c084fc",
        cyan: "#22d3ee",
        white: "#dce3e7",
        brightBlack: "#69747c",
        brightWhite: "#ffffff",
      },
    });
    fitAddon = new FitAddon.FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(byId("terminal-container"));
    terminal.onData((data) => {
      if (terminalSocket?.readyState === WebSocket.OPEN) {
        terminalSocket.send(JSON.stringify({type: "input", data}));
      }
    });
    terminal.onResize(({cols, rows}) => {
      if (terminalSocket?.readyState === WebSocket.OPEN) {
        terminalSocket.send(JSON.stringify({type: "resize", cols, rows}));
      }
    });
    const resizeObserver = new ResizeObserver(() => {
      if (byId("view-terminal").classList.contains("active")) {
        window.requestAnimationFrame(() => fitAddon.fit());
      }
    });
    resizeObserver.observe(byId("terminal-stage"));
    window.setTimeout(() => {
      fitAddon.fit();
      connectTerminal();
    }, 80);
    return;
  }
  window.setTimeout(() => fitAddon.fit(), 40);
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.viewTarget));
});

document.querySelectorAll("[data-view-link]").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.viewLink));
});

document.querySelectorAll("[data-subsystem][data-command]").forEach((button) => {
  button.addEventListener("click", () => {
    sendCommand(button.dataset.subsystem, button.dataset.command, button.dataset.confirm || "");
  });
});

byId("apply-route").addEventListener("click", () => {
  const route = byId("route-select").value;
  sendCommand("patrol", route, `Seleccionar ${route} como ruta activa?`);
});

byId("apply-speed").addEventListener("click", () => {
  sendCommand("patrol", `speed_${byId("speed-select").value}`);
});

byId("confirm-cancel").addEventListener("click", () => closeConfirm(false));
byId("confirm-accept").addEventListener("click", () => closeConfirm(true));
byId("confirm-modal").addEventListener("click", (event) => {
  if (event.target === byId("confirm-modal")) closeConfirm(false);
});

document.querySelectorAll(".filter-button").forEach((button) => {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    document.querySelectorAll(".filter-button").forEach((candidate) => {
      candidate.classList.toggle("active", candidate === button);
    });
    renderEvents();
  });
});

byId("clear-events").addEventListener("click", () => {
  events = [];
  renderEvents();
});

byId("terminal-reconnect").addEventListener("click", connectTerminal);
byId("terminal-clear").addEventListener("click", () => terminal?.clear());
byId("terminal-fullscreen").addEventListener("click", async () => {
  const stage = byId("terminal-stage");
  if (document.fullscreenElement) await document.exitFullscreen();
  else await stage.requestFullscreen();
  window.setTimeout(() => fitAddon?.fit(), 80);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !byId("confirm-modal").hidden) closeConfirm(false);
});

window.setInterval(() => {
  text("local-clock", new Date().toLocaleTimeString("es-VE", {hour12: false}));
  renderState();
}, 1000);

if (window.lucide) window.lucide.createIcons();
renderState();
renderEvents();
connectStateSocket();
const initialView = ["dashboard", "terminal", "events"].includes(location.hash.slice(1))
  ? location.hash.slice(1)
  : "dashboard";
switchView(initialView);
