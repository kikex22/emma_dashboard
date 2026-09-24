const dashboardState = {
  connections: {},
  orin_health: {},
  patrol: {},
  isa: {},
  base: {},
  navigation: {},
  map: {},
  robot_pose: {},
  route: {},
  vision: {},
  od_astra: {},
  od_arm: {},
  evaluation: {},
  processes: {},
  dashboard_video: {},
};

let events = [];
let evaluationReports = [];
let activeFilter = "all";
let stateSocket = null;
let terminal = null;
let fitAddon = null;
let terminalSocket = null;
let terminalStarted = false;
let terminalReconnectTimer = null;
let terminalFallbackActive = false;
const terminalDecoder = new TextDecoder();
let confirmResolver = null;
let routeSelectionDirty = false;
let speedSelectionDirty = false;
let navigationMapSelectionDirty = false;
const videoReceiverState = {
  astra: {loaded: false, loadCount: 0, lastLoadAt: 0, errorCount: 0},
  arm_cam: {loaded: false, loadCount: 0, lastLoadAt: 0, errorCount: 0},
};

const mapView = {
  raster: document.createElement("canvas"),
  revision: null,
  width: 0,
  height: 0,
  scale: 1,
  fitScale: 1,
  offsetX: 0,
  offsetY: 0,
  needsFit: true,
  drawPending: false,
  dragging: false,
  poseMode: false,
  poseDraft: null,
  posePointerId: null,
  pointerX: 0,
  pointerY: 0,
};

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
  badge.dataset.state = warning ? "warn" : online ? "online" : "offline";
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

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${total % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "--";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** index)).toFixed(index >= 3 ? 1 : 0)} ${units[index]}`;
}

function formatMbAsGb(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${(number / 1024).toFixed(1)} GB`;
}

function fileName(path) {
  if (!path) return "";
  return String(path).split("/").filter(Boolean).pop() || "";
}

function processVisualState(status) {
  const active = status?.active_state;
  if (active === "active") return "online";
  if (["activating", "deactivating", "reloading"].includes(active)) return "warn";
  if (active === "failed") return "error";
  return "offline";
}

function renderProcess(name, status = {}) {
  const row = byId(`process-${name}`);
  if (!row) return;

  row.dataset.state = processVisualState(status);
  const stateField = row.querySelector('[data-process-field="active_state"]');
  const pidField = row.querySelector('[data-process-field="main_pid"]');
  const uptimeField = row.querySelector('[data-process-field="uptime"]');
  if (stateField) stateField.textContent = String(status.active_state || "unknown").toUpperCase();
  if (pidField) pidField.textContent = Number(status.main_pid) > 0 ? String(status.main_pid) : "--";
  if (uptimeField) uptimeField.textContent = status.active_state === "active"
    ? formatDuration(status.uptime_sec)
    : "--";

  const loaded = status.load_state === "loaded";
  const busy = ["activating", "deactivating", "reloading"].includes(status.active_state);
  const active = status.active_state === "active";
  const start = row.querySelector('[data-process-action="start"]');
  const stop = row.querySelector('[data-process-action="stop"]');
  const restart = row.querySelector('[data-process-action="restart"]');
  if (start) start.disabled = !loaded || active || busy;
  if (stop) stop.disabled = !loaded || (!active && !busy);
  if (restart) restart.disabled = !loaded || busy;
  if (name === "nav") {
    const mapSelect = byId("nav-map-select");
    if (mapSelect) mapSelect.disabled = !loaded || active || busy || !mapSelect.value;
  }
}

function renderVisionProcessControls(name, status = {}, available = true) {
  const loaded = status.load_state === "loaded";
  const busy = ["activating", "deactivating", "reloading"].includes(status.active_state);
  const active = status.active_state === "active";
  document.querySelectorAll(`[data-process="${name}"][data-process-action]`).forEach((button) => {
    const action = button.dataset.processAction;
    if (action === "start") button.disabled = !loaded || !available || active || busy;
    else if (action === "stop") button.disabled = !loaded || (!active && !busy);
    else if (action === "restart") button.disabled = !loaded || !available || busy;
  });
}

function renderVisionService(id, status = {}) {
  const item = byId(id);
  if (!item) return;
  item.dataset.state = processVisualState(status);
  const value = item.querySelector("strong");
  if (value) value.textContent = String(status.active_state || "unknown").toUpperCase();
}

function visionPlayerUrl(camera) {
  const port = Number(dashboardState.vision?.webrtc_port) || 8889;
  return `${location.protocol}//${location.hostname}:${port}/${camera}/?autoplay=true&muted=true&controls=false&playsInline=true`;
}

function receiverCameraKey(camera) {
  return camera === "arm" ? "arm_cam" : camera;
}

function noteVisionFrameState(camera, eventName) {
  const key = receiverCameraKey(camera);
  const state = videoReceiverState[key];
  if (!state) return;
  if (eventName === "load") {
    state.loaded = true;
    state.loadCount += 1;
    state.lastLoadAt = Date.now() / 1000;
  } else if (eventName === "error") {
    state.loaded = false;
    state.errorCount += 1;
  } else if (eventName === "clear") {
    state.loaded = false;
  }
}

async function publishVideoReceiverStatus() {
  const cameras = {};
  [["astra", "astra"], ["arm", "arm_cam"]].forEach(([frameName, key]) => {
    const frameVisible = ["vision", "isa"].some((viewName) => {
      const frame = byId(`${viewName}-${frameName}-frame`);
      return frame && !frame.hidden && Boolean(frame.dataset.streamUrl);
    });
    const state = videoReceiverState[key] || {};
    cameras[key] = {
      visible: frameVisible,
      iframe_loaded: Boolean(state.loaded && frameVisible),
      load_count: Number(state.loadCount) || 0,
      error_count: Number(state.errorCount) || 0,
      last_load_at: Number(state.lastLoadAt) || 0,
    };
  });
  try {
    await fetch("/api/video/receiver-status", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({receiver: "dashboard", cameras}),
    });
  } catch (_error) {
    // La evaluacion conserva la ultima muestra valida si el dashboard pierde la red.
  }
}

function syncVisionPlayer(camera, ready) {
  ["vision", "isa"].forEach((viewName) => {
    const frame = byId(`${viewName}-${camera}-frame`);
    const empty = byId(`${viewName}-${camera}-empty`);
    const view = byId(`view-${viewName}`);
    if (!frame || !empty || !view) return;
    const shouldPlay = Boolean(ready && view.classList.contains("active"));
    const desired = shouldPlay ? visionPlayerUrl(camera) : "";
    if (frame.dataset.streamUrl !== desired) {
      frame.dataset.streamUrl = desired;
      if (desired) frame.src = desired;
      else {
        frame.removeAttribute("src");
        noteVisionFrameState(camera, "clear");
      }
    }
    frame.hidden = !shouldPlay;
    empty.hidden = shouldPlay;
  });
}

function renderRecording(camera, state, processState) {
  const strip = byId(`${camera}-recording`);
  if (!strip) return;

  const processActive = processState?.active_state === "active";
  const statusFresh = Number(state.recording_status_updated_at) > 0
    && Date.now() / 1000 - Number(state.recording_status_updated_at) < 3;
  const recording = statusFresh && Boolean(state.recording);
  const hasError = statusFresh && Boolean(state.error);
  const streams = [];
  if (state.raw_recording) streams.push("RAW");
  if (state.annotated_recording) streams.push("DET");

  strip.dataset.state = hasError ? "error" : recording ? "recording" : statusFresh ? "idle" : "offline";
  text(
    `${camera}-recording-state`,
    hasError ? "ERROR" : recording ? `REC ${streams.join(" + ")}` : statusFresh ? "LISTO" : "SIN CONTROL"
  );
  text(`${camera}-recording-time`, recording ? formatDuration(state.elapsed_sec) : "0s");

  const latest = fileName(state.annotated_last_saved) || fileName(state.raw_last_saved);
  const detail = hasError
    ? state.error
    : latest
      ? latest
      : statusFresh
        ? `${formatBytes(state.available_bytes)} libres`
        : "Esperando detector";
  text(`${camera}-recording-detail`, detail);

  const mode = byId(`${camera}-recording-mode`);
  if (mode) mode.disabled = recording || !processActive || !statusFresh;
  strip.querySelectorAll("[data-record-action]").forEach((button) => {
    const action = button.dataset.recordAction;
    if (action === "start") button.disabled = !processActive || !statusFresh || recording;
    else button.disabled = !recording;
  });
}

function renderVision() {
  const vision = dashboardState.vision || {};
  const astra = dashboardState.od_astra || {};
  const arm = dashboardState.od_arm || {};
  const processes = dashboardState.processes || {};
  const visionActive = processes.vision?.active_state === "active";
  const astraReady = Boolean(vision.astra_stream_ready);
  const armReady = Boolean(vision.arm_stream_ready);
  const gatewayOnline = Boolean(vision.gateway_online);

  setStateBadge(
    "vision-status",
    astraReady || armReady,
    "STREAMING",
    visionActive ? "INICIANDO" : "DETENIDO",
    visionActive && !astraReady && !armReady
  );

  const astraPanel = byId("camera-astra");
  const armPanel = byId("camera-arm");
  astraPanel.dataset.state = astraReady ? "online" : vision.astra_camera_connected ? "warn" : "offline";
  armPanel.dataset.state = armReady ? "online" : vision.arm_camera_connected ? "warn" : "offline";
  byId("isa-camera-astra").dataset.state = astraReady ? "online" : vision.astra_camera_connected ? "warn" : "offline";
  byId("isa-camera-arm").dataset.state = armReady ? "online" : vision.arm_camera_connected ? "warn" : "offline";
  text("isa-astra-state", astraReady ? "ONLINE" : "OFFLINE");
  text("isa-arm-state", armReady ? "ONLINE" : "OFFLINE");

  text("astra-camera-state", vision.astra_camera_connected ? "CAMARA CONECTADA" : "CAMARA AUSENTE");
  text("arm-camera-state", vision.arm_camera_connected ? "CAMARA CONECTADA" : "CAMARA AUSENTE");
  text("astra-stream", astraReady ? "ONLINE" : "OFFLINE");
  text("astra-fps", isFresh(astra, 4) ? fixed(astra.annotated_fps, 1) : "--");
  text("astra-inference", isFresh(astra, 4) ? fixed(astra.gpu_inference_mean_ms, 1, " ms") : "--");
  text("astra-detections", isFresh(astra, 3) ? astra.detection_count : "--");
  const firstDetection = Array.isArray(astra.detections) ? astra.detections[0] : null;
  text("astra-target", astra.target_class || firstDetection?.class_name || "--");
  text("astra-distance", fixed(astra.target_distance_m, 2, " m"));

  text("arm-stream", armReady ? "ONLINE" : "OFFLINE");
  text("arm-fps", isFresh(arm, 4) ? fixed(arm.annotated_fps, 1) : "--");
  text("arm-latency", isFresh(arm, 4) ? fixed(arm.processing_latency_ms, 1, " ms") : "--");
  const alignment = arm.alignment_command && arm.alignment_command !== "--"
    ? `${arm.alignment_command}${arm.alignment_angle === null || arm.alignment_angle === undefined ? "" : ` / ${fixed(arm.alignment_angle, 1, " deg")}`}`
    : "--";
  text("arm-alignment", alignment);
  text("arm-target", arm.class_name || arm.target_class || "--");
  text("arm-grasp", arm.grasp_state || "--");

  text(
    "vision-astra-reason",
    !vision.astra_camera_connected ? "Camara no conectada" : gatewayOnline ? "Esperando detector" : "Gateway detenido"
  );
  text(
    "vision-arm-reason",
    !vision.arm_camera_connected ? "Camara no conectada" : gatewayOnline ? "Esperando detector" : "Gateway detenido"
  );

  renderVisionService("vision-service-video", processes.video);
  renderVisionService("vision-service-depth", processes.depth);
  renderVisionService("vision-service-astra", processes.od_astra);
  renderVisionService("vision-service-arm", processes.od_arm);
  const anyVisionServiceActive = ["vision", "video", "depth", "od_astra", "od_arm"]
    .some((name) => ["active", "activating", "reloading"].includes(processes[name]?.active_state));
  const visionControlStatus = {
    ...processes.vision,
    active_state: anyVisionServiceActive ? "active" : processes.vision?.active_state,
  };
  renderVisionProcessControls("vision", visionControlStatus, true);
  renderVisionProcessControls("od_astra", processes.od_astra, Boolean(vision.astra_camera_connected));
  renderVisionProcessControls("od_arm", processes.od_arm, Boolean(vision.arm_camera_connected));
  renderRecording("astra", astra, processes.od_astra);
  renderRecording("arm", arm, processes.od_arm);
  const activeRecordings = Boolean(astra.recording) || Boolean(arm.recording);
  const recordable = [
    [astra, processes.od_astra],
    [arm, processes.od_arm],
  ].some(([state, process]) => process?.active_state === "active" && !state.recording);
  byId("record-all").disabled = !recordable;
  byId("save-all-recordings").disabled = !activeRecordings;
  syncVisionPlayer("astra", astraReady);
  syncVisionPlayer("arm", armReady);
}

function syncSelect(id, value) {
  const select = byId(id);
  if (!select || !value) return;
  if ([...select.options].some((option) => option.value === value)) {
    select.value = value;
  }
}

async function loadAvailableRoutes() {
  try {
    const response = await fetch("/api/routes");
    const payload = await response.json();
    if (!response.ok || !Array.isArray(payload.routes)) return;

    const select = byId("route-select");
    const userSelection = select.value;
    const activeRoute = dashboardState.patrol?.route;
    const desired = routeSelectionDirty ? userSelection : activeRoute || userSelection;
    select.replaceChildren();
    payload.routes.forEach((routeName) => {
      const option = document.createElement("option");
      option.value = routeName;
      option.textContent = routeName;
      select.append(option);
    });
    if ([...select.options].some((option) => option.value === desired)) {
      select.value = desired;
    }
  } catch (_error) {
    // El selector conserva sus opciones iniciales si el backend no responde.
  }
}

async function loadNavigationMaps() {
  try {
    const response = await fetch("/api/navigation/maps");
    const payload = await response.json();
    if (!response.ok || !Array.isArray(payload.maps)) return;

    const select = byId("nav-map-select");
    const userSelection = select.value;
    const desired = navigationMapSelectionDirty ? userSelection : payload.active || userSelection;
    select.replaceChildren();
    payload.maps.forEach((mapName) => {
      const option = document.createElement("option");
      option.value = mapName;
      option.textContent = mapName === payload.active ? `${mapName} (activo)` : mapName;
      select.append(option);
    });
    if ([...select.options].some((option) => option.value === desired)) {
      select.value = desired;
    }
    if (!select.value && select.options.length) select.selectedIndex = 0;
    renderProcess("nav", dashboardState.processes?.nav);
  } catch (_error) {
    // El estado del servicio sigue disponible aunque no se puedan listar mapas.
  }
}

function selectedEvaluationType() {
  return document.querySelector('input[name="evaluation-type"]:checked')?.value || "";
}

function selectedEvaluationValues(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
}

function evaluationElapsed(startedAt) {
  const started = Date.parse(startedAt || "");
  if (!Number.isFinite(started)) return "--";
  return formatDuration((Date.now() - started) / 1000);
}

function renderEvaluationReports() {
  const container = byId("evaluation-report-list");
  if (!container) return;
  container.replaceChildren();
  if (!evaluationReports.length) {
    const empty = document.createElement("div");
    empty.className = "evaluation-empty";
    empty.textContent = "Sin ensayos guardados.";
    container.append(empty);
    return;
  }

  evaluationReports.forEach((report) => {
    const row = document.createElement("div");
    row.className = "evaluation-report-row";
    const name = document.createElement("strong");
    name.textContent = report.name || report.run_id;
    name.title = report.run_id || "";
    const type = document.createElement("span");
    type.textContent = report.trial_type_label || report.trial_type || "SIN TIPO";
    const counts = report.counts || {};
    const values = [
      ["OK", counts.CONFORME || 0, "ok"],
      ["DESV", counts.LOGRADO_CON_DESVIACIONES || 0, "warn"],
      ["FAIL", counts.NO_LOGRADO || 0, "fail"],
      ["PEND", counts.PENDIENTE_EVIDENCIA || 0, "warn"],
    ];
    row.append(name, type);
    values.forEach(([label, value, state]) => {
      const count = document.createElement("span");
      count.className = `evaluation-report-count ${report.complete ? state : "warn"}`;
      count.textContent = report.complete ? `${label} ${value}` : label === "OK" ? "INCOMPLETO" : "--";
      row.append(count);
    });
    container.append(row);
  });
}

function renderEvaluation() {
  const evaluation = dashboardState.evaluation || {};
  const process = dashboardState.processes?.evaluation || {};
  const active = Boolean(evaluation.active);
  const collectorOnline = process.active_state === "active" || Boolean(evaluation.collector_online);
  const selected = selectedEvaluationType();

  setStateBadge(
    "evaluation-status",
    active,
    collectorOnline ? "EN CURSO" : "RECUPERAR",
    "SIN ENSAYO",
    active && !collectorOnline
  );
  setStateBadge("evaluation-collector", collectorOnline, "ONLINE", "OFFLINE");
  const live = byId("evaluation-live");
  if (live) live.dataset.state = active ? "online" : "offline";
  text("evaluation-live-type", evaluation.trial_type_label || evaluation.trial_type);
  text("evaluation-live-name", evaluation.name || evaluation.run_id);
  text("evaluation-live-duration", active ? evaluationElapsed(evaluation.started_at) : "--");
  text("evaluation-live-topics", active ? evaluation.seen_topics ?? 0 : "--");
  text("evaluation-live-interventions", active ? evaluation.interventions ?? 0 : "--");
  text("evaluation-live-clock", evaluation.clock_synchronized ? "SINCRONIZADO" : "NO SINCRONIZADO");
  text(
    "evaluation-live-message",
    active
      ? collectorOnline
        ? `Recolectando evidencia en ${evaluation.run_id || "el ensayo activo"}.`
        : "El ensayo quedo abierto pero el recolector esta detenido. Finalizar lo levantara para recuperar y generar el reporte."
      : selected
        ? "El ensayo observara ROS 2; inicia el modulo operativo antes de comenzar."
        : "Selecciona una prueba para comenzar."
  );

  const odOptions = byId("evaluation-od-options");
  if (odOptions) odOptions.hidden = selected !== "od_live";
  const scene = byId("evaluation-scene")?.value || "free";
  if (byId("evaluation-classes")) byId("evaluation-classes").disabled = scene === "free";

  document.querySelectorAll('input[name="evaluation-type"], #evaluation-location, #evaluation-operator, #evaluation-name, #evaluation-notes, #evaluation-scene, input[name="evaluation-camera"], input[name="evaluation-class"]').forEach((control) => {
    control.disabled = active;
  });
  byId("evaluation-start").disabled = active || !selected || !evaluation.clock_synchronized;
  byId("evaluation-stop").disabled = !active;
  byId("evaluation-add-note").disabled = !active;
  byId("evaluation-add-intervention").disabled = !active;
}

async function loadEvaluation() {
  try {
    const response = await fetch("/api/evaluation");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo leer Evaluation");
    dashboardState.evaluation = payload.evaluation || {};
    evaluationReports = payload.reports || [];
    renderEvaluation();
    renderEvaluationReports();
  } catch (error) {
    toast(error.message || "Error leyendo Evaluation", "error");
  }
}

async function startEvaluation() {
  const trialType = selectedEvaluationType();
  if (!trialType) return;
  const payload = {
    trial_type: trialType,
    location: byId("evaluation-location").value,
    operator: byId("evaluation-operator").value,
    name: byId("evaluation-name").value,
    notes: byId("evaluation-notes").value,
    scene_mode: byId("evaluation-scene").value,
    cameras: selectedEvaluationValues("evaluation-camera"),
    expected_classes: selectedEvaluationValues("evaluation-class"),
  };
  try {
    byId("evaluation-start").disabled = true;
    const response = await fetch("/api/evaluation/start", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "No se pudo iniciar el ensayo");
    dashboardState.evaluation = result.evaluation || dashboardState.evaluation;
    renderEvaluation();
    toast("Evaluation: ensayo iniciado");
    (result.warnings || []).forEach((warning) => toast(warning, "error"));
  } catch (error) {
    toast(error.message || "Error iniciando Evaluation", "error");
    renderEvaluation();
  }
}

async function stopEvaluation(confirmation = "") {
  if (confirmation && !(await confirmAction(confirmation))) return;
  try {
    byId("evaluation-stop").disabled = true;
    const response = await fetch("/api/evaluation/stop", {method: "POST"});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo finalizar el ensayo");
    dashboardState.evaluation = payload.evaluation || {};
    evaluationReports = payload.reports || evaluationReports;
    renderEvaluation();
    renderEvaluationReports();
    toast("Evaluation: reporte generado");
  } catch (error) {
    toast(error.message || "Error finalizando Evaluation", "error");
    renderEvaluation();
  }
}

async function addEvaluationEntry(action) {
  const input = byId("evaluation-entry-text");
  const value = input.value.trim();
  if (!value) {
    toast("Escribe una nota o motivo", "error");
    return;
  }
  try {
    const response = await fetch(`/api/evaluation/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: value}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo registrar");
    input.value = "";
    toast(action === "note" ? "Nota registrada" : "Intervencion registrada");
  } catch (error) {
    toast(error.message || "Error registrando evidencia", "error");
  }
}

function renderState() {
  const connections = dashboardState.connections || {};
  const orinHealth = dashboardState.orin_health || {};
  const patrol = dashboardState.patrol || {};
  const isa = dashboardState.isa || {};
  const base = dashboardState.base || {};
  const navigation = dashboardState.navigation || {};
  const map = dashboardState.map || {};
  const robotPose = dashboardState.robot_pose || {};
  const route = dashboardState.route || {};
  const processes = dashboardState.processes || {};

  const orinOnline = Boolean(connections.orin);
  const rosOnline = Boolean(connections.ros);
  const patrolOnline = Boolean(patrol.online) && isFresh(patrol);
  const isaOnline = Boolean(isa.online) && isFresh(isa);

  setStateBadge("orin-pill", orinOnline, "ORIN", "ORIN");
  setStateBadge("ros-pill", rosOnline, "ROS 2", "ROS 2");
  setStateBadge("patrol-online", patrolOnline, "ONLINE", "OFFLINE");
  setStateBadge("isa-online", isaOnline, "ONLINE", "OFFLINE");
  setStateBadge("isa-ops-online", isaOnline, "ONLINE", "OFFLINE");

  text("rail-orin", orinOnline ? "ONLINE" : "OFFLINE");
  text("rail-ros", rosOnline ? "ONLINE" : "OFFLINE");
  const navProcessActive = processes.nav?.active_state === "active";
  text("rail-nav2", navigation.ready ? "READY" : navProcessActive ? "INICIANDO" : "OFFLINE");
  text("rail-owner", base.owner || patrol.base_control_owner);
  const healthFresh = Boolean(orinHealth.online) && isFresh(orinHealth, 4);
  const healthPanel = byId("orin-health");
  if (healthPanel) healthPanel.dataset.state = healthFresh ? orinHealth.status || "ok" : "offline";
  text("orin-health-state", healthFresh ? String(orinHealth.status || "ok").toUpperCase() : "SIN DATOS");
  text("orin-health-cpu", healthFresh ? fixed(orinHealth.cpu_percent, 1, "%") : "--");
  text("orin-health-gpu", healthFresh ? fixed(orinHealth.gpu_percent, 0, "%") : "--");
  text(
    "orin-health-ram",
    healthFresh
      ? `${formatMbAsGb(orinHealth.ram_used_mb)} / ${formatMbAsGb(orinHealth.ram_total_mb)}`
      : "--"
  );
  text("orin-health-temp", healthFresh ? fixed(orinHealth.temp_c, 1, " C") : "--");
  text("orin-health-power", healthFresh ? fixed(orinHealth.power_w, 2, " W") : "--");

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
  const bboxArea = Number(isa.arm_bbox_area);
  const stopArea = Number(isa.arm_active_stop_area);
  text(
    "isa-bbox",
    isaOnline && Number.isFinite(bboxArea) && bboxArea > 0
      ? `${Math.round(bboxArea)} / ${Number.isFinite(stopArea) && stopArea > 0 ? `${Math.round(stopArea)} (${Math.round(bboxArea / stopArea * 100)}%)` : "--"}`
      : "--"
  );
  const contact = isa.contact_diag || {};
  const contactReason = contact.reason || contact.status || contact.label || "";
  text(
    "isa-contact",
    isaOnline
      ? `${boolLabel(Boolean(isa.contact_diag_ready), "READY", "NO READY")}${contactReason ? ` / ${contactReason}` : ""}`
      : "--"
  );
  text(
    "isa-gripper",
    isaOnline
      ? isa.grasp_verify_waiting
        ? "VERIFICANDO"
        : isa.grasp_verify_last_status || "LISTO"
      : "--"
  );
  text("isa-base-owner", isaOnline ? isa.base_control_owner || "--" : "--");
  text("isa-patrol", isa.patrol_status);

  text("isa-ops-state", isaOnline ? isa.state : "sin datos");
  text("isa-ops-mode", isa.mode);
  text("isa-ops-target", isa.target);
  text("isa-ops-distance", fixed(isa.distance, 2, " m"));
  text("isa-ops-offset", fixed(isa.offset, 3));
  text("isa-ops-bin", isa.bin_active ? "ACTIVO" : "INACTIVO");
  text(
    "isa-ops-bbox",
    isaOnline && Number.isFinite(bboxArea) && bboxArea > 0
      ? `${Math.round(bboxArea)} / ${Number.isFinite(stopArea) && stopArea > 0 ? `${Math.round(stopArea)} (${Math.round(bboxArea / stopArea * 100)}%)` : "--"}`
      : "--"
  );
  text(
    "isa-ops-contact",
    isaOnline
      ? `${boolLabel(Boolean(isa.contact_diag_ready), "READY", "NO READY")}${contactReason ? ` / ${contactReason}` : ""}`
      : "--"
  );
  text(
    "isa-ops-gripper",
    isaOnline ? (isa.grasp_verify_waiting ? "VERIFICANDO" : isa.grasp_verify_last_status || "LISTO") : "--"
  );
  text("isa-ops-owner", isaOnline ? isa.base_control_owner || "--" : "--");

  text("base-state", `${base.owner || "--"} / ${base.state || "sin datos"}`);
  text(
    "base-estop",
    base.updated_at ? `E-STOP ${boolLabel(base.estop, "ACTIVO", "OK")}` : "E-STOP --"
  );
  if (routeSelectionDirty && patrol.route === byId("route-select").value) {
    routeSelectionDirty = false;
  }
  if (!routeSelectionDirty) syncSelect("route-select", patrol.route);
  if (speedSelectionDirty && patrol.speed === byId("speed-select").value) {
    speedSelectionDirty = false;
  }
  if (!speedSelectionDirty) syncSelect("speed-select", patrol.speed);
  text("terminal-host", location.hostname || connections.orin_host || "orin");

  renderProcess("nav", processes.nav);
  renderProcess("patrol", processes.patrol);
  renderProcess("isa", processes.isa);
  renderVision();
  renderEvaluation();

  const mapAvailable = Boolean(map.available && map.width && map.height);
  const poseFresh = Boolean(robotPose.available) && isFresh(robotPose, 2.5);
  setStateBadge("map-status", mapAvailable, "MAPA", "SIN MAPA", !poseFresh && mapAvailable);
  text("map-frame", mapAvailable ? `FRAME ${map.frame_id || "map"}` : "FRAME --");
  text(
    "map-robot-pose",
    poseFresh ? `x ${fixed(robotPose.x, 2)}  y ${fixed(robotPose.y, 2)}` : "SIN TF"
  );
  text("map-route-status", route.points?.length ? `${route.points.length} PUNTOS` : "SIN PUNTOS");
  text("map-pose-mode", mapView.poseMode ? "REUBICAR" : "NORMAL");
  byId("map-initial-pose")?.classList.toggle("active", mapView.poseMode);
  byId("map-empty").hidden = mapAvailable;
  prepareMapRaster();
  requestMapDraw();
}

function prepareMapRaster() {
  const map = dashboardState.map || {};
  if (!map.available || !map.width || !map.height || !Array.isArray(map.data_rle)) return;
  if (mapView.revision === map.revision) return;

  const width = Number(map.width);
  const height = Number(map.height);
  const context = mapView.raster.getContext("2d");
  mapView.raster.width = width;
  mapView.raster.height = height;
  const image = context.createImageData(width, height);
  let sourceIndex = 0;

  for (let index = 0; index < map.data_rle.length; index += 2) {
    const value = Number(map.data_rle[index]);
    const count = Number(map.data_rle[index + 1]);
    for (let offset = 0; offset < count && sourceIndex < width * height; offset += 1) {
      const sourceY = Math.floor(sourceIndex / width);
      const sourceX = sourceIndex % width;
      const targetIndex = ((height - 1 - sourceY) * width + sourceX) * 4;
      let red;
      let green;
      let blue;
      if (value < 0) {
        red = 18;
        green = 23;
        blue = 26;
      } else {
        const occupancy = Math.max(0, Math.min(100, value));
        const shade = Math.round(235 - occupancy * 2.08);
        red = shade;
        green = Math.min(239, shade + 3);
        blue = Math.min(241, shade + 5);
      }
      image.data[targetIndex] = red;
      image.data[targetIndex + 1] = green;
      image.data[targetIndex + 2] = blue;
      image.data[targetIndex + 3] = 255;
      sourceIndex += 1;
    }
  }

  context.putImageData(image, 0, 0);
  const dimensionsChanged = mapView.width !== width || mapView.height !== height;
  mapView.width = width;
  mapView.height = height;
  mapView.revision = map.revision;
  if (dimensionsChanged || mapView.fitScale === 1) mapView.needsFit = true;
}

function canvasMetrics() {
  const canvas = byId("map-canvas");
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const ratio = window.devicePixelRatio || 1;
  const pixelWidth = Math.max(1, Math.round(rect.width * ratio));
  const pixelHeight = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  return {canvas, width: rect.width, height: rect.height, ratio};
}

function fitMap() {
  const metrics = canvasMetrics();
  if (!metrics || !mapView.width || !mapView.height) return;
  const scale = Math.min(
    metrics.width / mapView.width,
    metrics.height / mapView.height
  ) * 0.92;
  mapView.scale = Math.max(0.02, scale);
  mapView.fitScale = mapView.scale;
  mapView.offsetX = (metrics.width - mapView.width * mapView.scale) / 2;
  mapView.offsetY = (metrics.height - mapView.height * mapView.scale) / 2;
  mapView.needsFit = false;
  byId("map-follow").checked = false;
  requestMapDraw();
}

function worldToGrid(x, y) {
  const map = dashboardState.map || {};
  const origin = map.origin || {};
  const resolution = Number(map.resolution) || 1;
  const yaw = Number(origin.yaw) || 0;
  const dx = Number(x) - (Number(origin.x) || 0);
  const dy = Number(y) - (Number(origin.y) || 0);
  return {
    x: (Math.cos(yaw) * dx + Math.sin(yaw) * dy) / resolution,
    y: mapView.height - (-Math.sin(yaw) * dx + Math.cos(yaw) * dy) / resolution,
  };
}

function gridToWorld(point) {
  const map = dashboardState.map || {};
  const origin = map.origin || {};
  const resolution = Number(map.resolution) || 1;
  const yaw = Number(origin.yaw) || 0;
  const localX = Number(point.x) * resolution;
  const localY = (mapView.height - Number(point.y)) * resolution;
  return {
    x: (Number(origin.x) || 0) + Math.cos(yaw) * localX - Math.sin(yaw) * localY,
    y: (Number(origin.y) || 0) + Math.sin(yaw) * localX + Math.cos(yaw) * localY,
  };
}

function gridToCanvas(point) {
  return {
    x: mapView.offsetX + point.x * mapView.scale,
    y: mapView.offsetY + point.y * mapView.scale,
  };
}

function canvasToGrid(x, y) {
  return {
    x: (Number(x) - mapView.offsetX) / mapView.scale,
    y: (Number(y) - mapView.offsetY) / mapView.scale,
  };
}

function canvasToWorld(x, y) {
  return gridToWorld(canvasToGrid(x, y));
}

function worldToCanvas(x, y) {
  return gridToCanvas(worldToGrid(x, y));
}

function centerRobot(redraw = true) {
  const pose = dashboardState.robot_pose || {};
  const metrics = canvasMetrics();
  if (!metrics || !pose.available || !mapView.width) return;
  const grid = worldToGrid(pose.x, pose.y);
  mapView.offsetX = metrics.width / 2 - grid.x * mapView.scale;
  mapView.offsetY = metrics.height / 2 - grid.y * mapView.scale;
  if (redraw) requestMapDraw();
}

function zoomMap(factor, anchorX = null, anchorY = null) {
  const metrics = canvasMetrics();
  if (!metrics || !mapView.width) return;
  const x = anchorX ?? metrics.width / 2;
  const y = anchorY ?? metrics.height / 2;
  const minimum = Math.max(0.01, mapView.fitScale * 0.25);
  const maximum = Math.max(minimum, mapView.fitScale * 12);
  const next = Math.max(minimum, Math.min(maximum, mapView.scale * factor));
  const applied = next / mapView.scale;
  mapView.offsetX = x - (x - mapView.offsetX) * applied;
  mapView.offsetY = y - (y - mapView.offsetY) * applied;
  mapView.scale = next;
  requestMapDraw();
}

function drawRoute(context) {
  const points = dashboardState.route?.points || [];
  if (!points.length) return;
  const activeIndex = Number(dashboardState.patrol?.waypoint_index ?? -1);

  context.save();
  context.lineJoin = "round";
  context.lineCap = "round";
  context.lineWidth = 3;
  context.strokeStyle = "#16b8d0";
  context.beginPath();
  points.forEach((point, index) => {
    const screen = worldToCanvas(point.x, point.y);
    if (index === 0) context.moveTo(screen.x, screen.y);
    else context.lineTo(screen.x, screen.y);
  });
  context.stroke();

  points.forEach((point, index) => {
    const screen = worldToCanvas(point.x, point.y);
    const active = index === activeIndex;
    context.beginPath();
    context.arc(screen.x, screen.y, active ? 8 : 6, 0, Math.PI * 2);
    context.fillStyle = active ? "#f4b942" : "#0b1114";
    context.fill();
    context.lineWidth = 2;
    context.strokeStyle = active ? "#fff1bb" : "#22d3ee";
    context.stroke();
    context.fillStyle = active ? "#17130a" : "#e8f7fa";
    context.font = "600 10px ui-monospace, monospace";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(String(point.label || index + 1).replace(" BIN", ""), screen.x, screen.y);

    const heading = -(Number(point.yaw) - Number(dashboardState.map?.origin?.yaw || 0));
    context.beginPath();
    context.moveTo(screen.x + Math.cos(heading) * 10, screen.y + Math.sin(heading) * 10);
    context.lineTo(screen.x + Math.cos(heading) * 16, screen.y + Math.sin(heading) * 16);
    context.strokeStyle = "#f4b942";
    context.lineWidth = 2;
    context.stroke();
  });
  context.restore();
}

function drawRobot(context) {
  const pose = dashboardState.robot_pose || {};
  if (!pose.available || !isFresh(pose, 2.5)) return;
  const screen = worldToCanvas(pose.x, pose.y);
  const angle = -(Number(pose.yaw) - Number(dashboardState.map?.origin?.yaw || 0));

  context.save();
  context.translate(screen.x, screen.y);
  context.rotate(angle);
  context.shadowColor = "rgb(63 227 139 / 70%)";
  context.shadowBlur = 12;
  context.beginPath();
  context.moveTo(16, 0);
  context.lineTo(-10, -9);
  context.lineTo(-5, 0);
  context.lineTo(-10, 9);
  context.closePath();
  context.fillStyle = "#3fe38b";
  context.fill();
  context.shadowBlur = 0;
  context.lineWidth = 2;
  context.strokeStyle = "#06110b";
  context.stroke();
  context.restore();
}

function drawInitialPosePreview(context) {
  if (!mapView.poseDraft) return;
  const draft = mapView.poseDraft;
  const screen = worldToCanvas(draft.x, draft.y);
  const angle = -(Number(draft.yaw) - Number(dashboardState.map?.origin?.yaw || 0));

  context.save();
  context.translate(screen.x, screen.y);
  context.rotate(angle);
  context.shadowColor = "rgb(244 185 66 / 75%)";
  context.shadowBlur = 16;
  context.beginPath();
  context.moveTo(20, 0);
  context.lineTo(-12, -11);
  context.lineTo(-6, 0);
  context.lineTo(-12, 11);
  context.closePath();
  context.fillStyle = "#f4b942";
  context.fill();
  context.shadowBlur = 0;
  context.lineWidth = 2;
  context.strokeStyle = "#17130a";
  context.stroke();
  context.beginPath();
  context.arc(0, 0, 4, 0, Math.PI * 2);
  context.fillStyle = "#090b0d";
  context.fill();
  context.restore();
}

function drawMap() {
  mapView.drawPending = false;
  const metrics = canvasMetrics();
  if (!metrics) return;
  if (mapView.needsFit && mapView.width) fitMap();

  const context = metrics.canvas.getContext("2d");
  context.setTransform(metrics.ratio, 0, 0, metrics.ratio, 0, 0);
  context.clearRect(0, 0, metrics.width, metrics.height);
  context.fillStyle = "#060809";
  context.fillRect(0, 0, metrics.width, metrics.height);
  if (!mapView.width || !dashboardState.map?.available) return;

  if (byId("map-follow").checked && dashboardState.robot_pose?.available) centerRobot(false);

  context.imageSmoothingEnabled = false;
  context.drawImage(
    mapView.raster,
    mapView.offsetX,
    mapView.offsetY,
    mapView.width * mapView.scale,
    mapView.height * mapView.scale
  );
  context.strokeStyle = "#4b5860";
  context.lineWidth = 1;
  context.strokeRect(
    mapView.offsetX,
    mapView.offsetY,
    mapView.width * mapView.scale,
    mapView.height * mapView.scale
  );
  context.save();
  context.beginPath();
  context.rect(
    mapView.offsetX,
    mapView.offsetY,
    mapView.width * mapView.scale,
    mapView.height * mapView.scale
  );
  context.clip();
  drawRoute(context);
  drawRobot(context);
  drawInitialPosePreview(context);
  context.restore();

  const zoom = mapView.fitScale ? Math.round((mapView.scale / mapView.fitScale) * 100) : 100;
  text("map-scale", `${zoom} %`);
}

function requestMapDraw() {
  if (mapView.drawPending) return;
  mapView.drawPending = true;
  window.requestAnimationFrame(drawMap);
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
  if (confirmation && !(await confirmAction(confirmation))) return false;
  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({subsystem, command}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo enviar el comando");
    toast(`${subsystem.toUpperCase()}: ${command}`);
    return true;
  } catch (error) {
    toast(error.message || "Error enviando comando", "error");
    return false;
  }
}

async function sendInitialPose(pose) {
  if (!pose) return false;
  const confirmed = await confirmAction(
    `Reubicar robot en x=${pose.x.toFixed(2)} y=${pose.y.toFixed(2)} yaw=${Math.round(pose.yaw * 180 / Math.PI)} grados?`
  );
  if (!confirmed) return false;
  try {
    const response = await fetch("/api/navigation/initial-pose", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        x: pose.x,
        y: pose.y,
        yaw: pose.yaw,
        frame_id: dashboardState.map?.frame_id || "map",
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo publicar /initialpose");
    toast("Pose inicial publicada");
    return true;
  } catch (error) {
    toast(error.message || "Error publicando pose inicial", "error");
    return false;
  }
}

async function sendRecording(camera, action, confirmation = "") {
  if (confirmation && !(await confirmAction(confirmation))) return false;
  let command = action;
  if (action === "start") {
    const mode = byId(`${camera}-recording-mode`)?.value || "both";
    command = `start_${mode}`;
  }
  try {
    const response = await fetch(
      `/api/recordings/${encodeURIComponent(camera)}/${encodeURIComponent(command)}`,
      {method: "POST"}
    );
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo controlar la grabacion");
    toast(`REC ${camera.toUpperCase()}: ${command}`);
    return true;
  } catch (error) {
    toast(error.message || "Error controlando la grabacion", "error");
    return false;
  }
}

async function sendProcessAction(name, action, confirmation = "") {
  if (confirmation && !(await confirmAction(confirmation))) return;
  try {
    const options = {method: "POST"};
    const navActive = dashboardState.processes?.nav?.active_state === "active";
    const selectsMap = (name === "nav" && ["start", "restart"].includes(action))
      || (name === "patrol" && ["start", "restart"].includes(action) && !navActive);
    if (selectsMap) {
      const mapName = byId("nav-map-select").value;
      if (!mapName) throw new Error("Selecciona un mapa de navegacion");
      options.headers = {"Content-Type": "application/json"};
      options.body = JSON.stringify({map: mapName});
    }
    const response = await fetch(`/api/processes/${encodeURIComponent(name)}/${action}`, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo controlar el proceso");
    dashboardState.processes = {
      ...dashboardState.processes,
      [name]: payload.process,
    };
    if (payload.navigation_map) navigationMapSelectionDirty = false;
    renderState();
    await loadNavigationMaps();
    toast(`${payload.process.label}: ${action}`);
  } catch (error) {
    toast(error.message || "Error controlando el proceso", "error");
  }
}

async function controllerEmergencyReset() {
  const confirmed = await confirmAction(
    "C33 detiene la base y reinicia el USB del controller. Usarlo solo si el controller se pego o congelo. Ejecutar ahora?"
  );
  if (!confirmed) return;

  try {
    toast("C33: ejecutando reset del controller...");
    const response = await fetch("/api/emergency/controller-reset", {method: "POST"});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudo ejecutar C33");
    toast("C33: controller reset ejecutado");
    const processesResponse = await fetch("/api/processes");
    const processesPayload = await processesResponse.json();
    if (processesResponse.ok) {
      dashboardState.processes = processesPayload.processes || dashboardState.processes;
      renderState();
    }
  } catch (error) {
    toast(error.message || "Error ejecutando C33", "error");
  }
}

async function showProcessLogs(name) {
  const modal = byId("logs-modal");
  text("logs-title", `Logs / ${name.toUpperCase()}`);
  byId("logs-content").textContent = "Cargando...";
  modal.hidden = false;
  try {
    const response = await fetch(`/api/processes/${encodeURIComponent(name)}/logs?lines=180`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "No se pudieron leer los logs");
    byId("logs-content").textContent = payload.logs || "Sin entradas en el journal";
    byId("logs-content").scrollTop = byId("logs-content").scrollHeight;
  } catch (error) {
    byId("logs-content").textContent = error.message || "Error leyendo logs";
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
  if (viewName === "carolina") window.setTimeout(requestMapDraw, 40);
  if (viewName === "evaluation") loadEvaluation();
  if (viewName === "vision" || viewName === "isa") window.setTimeout(renderVision, 40);
  else {
    syncVisionPlayer("astra", false);
    syncVisionPlayer("arm", false);
  }
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

function fitTerminal() {
  if (!fitAddon || !terminal) return false;
  const stage = byId("terminal-stage");
  const bounds = stage?.getBoundingClientRect();
  if (!bounds || bounds.width < 40 || bounds.height < 40) return false;
  try {
    fitAddon.fit();
    return true;
  } catch (error) {
    console.warn("No se pudo ajustar la terminal al viewport", error);
    return false;
  }
}

function isAppleTouchDevice() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function sendTerminalInput(data) {
  if (terminalSocket?.readyState !== WebSocket.OPEN) {
    updateTerminalBadge("offline");
    return false;
  }
  terminalSocket.send(JSON.stringify({type: "input", data}));
  return true;
}

function activateTerminalFallback(error) {
  terminalFallbackActive = true;
  const stage = byId("terminal-stage");
  const fallback = byId("terminal-fallback");
  stage.classList.add("terminal-native", "terminal-mobile-input");
  fallback.hidden = false;
  fallback.textContent = `Terminal compatible activa.\n${error?.message || "xterm no disponible en este navegador"}\n\n`;
}

function writeTerminalOutput(data) {
  if (terminal && !terminalFallbackActive) {
    terminal.write(data);
    return;
  }
  const fallback = byId("terminal-fallback");
  if (!fallback) return;
  fallback.hidden = false;
  fallback.textContent += terminalDecoder.decode(data, {stream: true});
  if (fallback.textContent.length > 120000) {
    fallback.textContent = fallback.textContent.slice(-90000);
  }
  fallback.scrollTop = fallback.scrollHeight;
}

function connectTerminal() {
  if (terminalReconnectTimer) {
    window.clearTimeout(terminalReconnectTimer);
    terminalReconnectTimer = null;
  }
  if (terminalSocket) {
    terminalSocket.onclose = null;
    terminalSocket.close();
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/terminal`);
  terminalSocket = socket;
  socket.binaryType = "arraybuffer";
  updateTerminalBadge("connecting");

  socket.onopen = () => {
    if (socket !== terminalSocket) return;
    socket.send(JSON.stringify({
      type: "resize",
      cols: terminal?.cols || 100,
      rows: terminal?.rows || 30,
    }));
  };

  socket.onmessage = (message) => {
    if (socket !== terminalSocket) return;
    if (typeof message.data === "string") {
      let payload;
      try {
        payload = JSON.parse(message.data);
      } catch (_error) {
        return;
      }
      if (payload.type === "status") {
        updateTerminalBadge(payload.value, payload.message || "");
      }
      return;
    }
    writeTerminalOutput(new Uint8Array(message.data));
  };

  socket.onclose = () => {
    if (socket !== terminalSocket) return;
    updateTerminalBadge("offline");
    if (byId("view-terminal").classList.contains("active")) {
      terminalReconnectTimer = window.setTimeout(connectTerminal, 1800);
    }
  };
  socket.onerror = () => {
    if (socket === terminalSocket) updateTerminalBadge("error", "fallo de conexion local");
  };
}

function startTerminal() {
  if (!terminalStarted) {
    terminalStarted = true;
    if (isAppleTouchDevice()) {
      byId("terminal-stage").classList.add("terminal-mobile-input");
    }
    // The connection cannot depend on xterm: older Safari versions can fail
    // while creating its hidden textarea before a WebSocket is requested.
    connectTerminal();
    try {
      if (typeof window.Terminal !== "function" || !window.FitAddon?.FitAddon) {
        throw new Error("xterm no es compatible con esta version de Safari");
      }
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
      byId("terminal-stage").addEventListener("pointerdown", () => terminal.focus());
      terminal.onData(sendTerminalInput);
      terminal.onResize(({cols, rows}) => {
        if (terminalSocket?.readyState === WebSocket.OPEN) {
          terminalSocket.send(JSON.stringify({type: "resize", cols, rows}));
        }
      });
      const resizeObserver = new ResizeObserver(() => {
        if (byId("view-terminal").classList.contains("active")) {
          window.requestAnimationFrame(fitTerminal);
        }
      });
      resizeObserver.observe(byId("terminal-stage"));
      window.setTimeout(fitTerminal, 80);
    } catch (error) {
      console.error("Terminal xterm no disponible", error);
      activateTerminalFallback(error);
    }
    return;
  }
  window.setTimeout(fitTerminal, 40);
}

document.querySelectorAll("iframe[id$=\"-astra-frame\"]").forEach((frame) => {
  frame.addEventListener("load", () => noteVisionFrameState("astra", "load"));
  frame.addEventListener("error", () => noteVisionFrameState("astra", "error"));
});

document.querySelectorAll("iframe[id$=\"-arm-frame\"]").forEach((frame) => {
  frame.addEventListener("load", () => noteVisionFrameState("arm", "load"));
  frame.addEventListener("error", () => noteVisionFrameState("arm", "error"));
});

window.setInterval(publishVideoReceiverStatus, 1000);

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

byId("send-isa-command").addEventListener("click", () => {
  const command = byId("isa-command-select").value;
  if (command) sendCommand("isa", command);
});

byId("controller-reset-c33").addEventListener("click", controllerEmergencyReset);

document.querySelectorAll('input[name="evaluation-type"]').forEach((input) => {
  input.addEventListener("change", renderEvaluation);
});
byId("evaluation-scene").addEventListener("change", renderEvaluation);
byId("evaluation-refresh").addEventListener("click", loadEvaluation);
byId("evaluation-start").addEventListener("click", startEvaluation);
byId("evaluation-stop").addEventListener("click", () => {
  stopEvaluation(byId("evaluation-stop").dataset.confirm || "");
});
byId("evaluation-add-note").addEventListener("click", () => addEvaluationEntry("note"));
byId("evaluation-add-intervention").addEventListener("click", () => addEvaluationEntry("intervention"));

document.querySelectorAll("[data-process][data-process-action]").forEach((button) => {
  button.addEventListener("click", () => {
    sendProcessAction(
      button.dataset.process,
      button.dataset.processAction,
      button.dataset.confirm || ""
    );
  });
});

document.querySelectorAll("[data-process-logs]").forEach((button) => {
  button.addEventListener("click", () => showProcessLogs(button.dataset.processLogs));
});

document.querySelectorAll("[data-record-camera][data-record-action]").forEach((button) => {
  button.addEventListener("click", () => {
    sendRecording(
      button.dataset.recordCamera,
      button.dataset.recordAction,
      button.dataset.confirm || ""
    );
  });
});

byId("record-all").addEventListener("click", async () => {
  const processes = dashboardState.processes || {};
  const cameras = [
    ["astra", "od_astra"],
    ["arm", "od_arm"],
  ].filter(([, process]) => processes[process]?.active_state === "active");
  await Promise.all(cameras.map(([camera]) => {
    const select = byId(`${camera}-recording-mode`);
    if (select) select.value = "both";
    return sendRecording(camera, "start");
  }));
});

byId("save-all-recordings").addEventListener("click", async () => {
  const cameras = ["astra", "arm"].filter((camera) => {
    const state = camera === "astra" ? dashboardState.od_astra : dashboardState.od_arm;
    return Boolean(state?.recording);
  });
  await Promise.all(cameras.map((camera) => sendRecording(camera, "save")));
});

byId("nav-map-select").addEventListener("change", () => {
  navigationMapSelectionDirty = true;
});

byId("route-select").addEventListener("change", () => {
  routeSelectionDirty = true;
});

byId("apply-route").addEventListener("click", async () => {
  const route = byId("route-select").value;
  const sent = await sendCommand("patrol", route, `Seleccionar ${route} como ruta activa?`);
  if (!sent) {
    routeSelectionDirty = false;
    renderState();
  }
});

byId("speed-select").addEventListener("change", () => {
  speedSelectionDirty = true;
});

byId("apply-speed").addEventListener("click", async () => {
  const sent = await sendCommand("patrol", `speed_${byId("speed-select").value}`);
  if (!sent) {
    speedSelectionDirty = false;
    renderState();
  }
});

byId("confirm-cancel").addEventListener("click", () => closeConfirm(false));
byId("confirm-accept").addEventListener("click", () => closeConfirm(true));
byId("confirm-modal").addEventListener("click", (event) => {
  if (event.target === byId("confirm-modal")) closeConfirm(false);
});

byId("logs-close").addEventListener("click", () => {
  byId("logs-modal").hidden = true;
});
byId("logs-modal").addEventListener("click", (event) => {
  if (event.target === byId("logs-modal")) byId("logs-modal").hidden = true;
});

byId("map-zoom-in").addEventListener("click", () => zoomMap(1.25));
byId("map-zoom-out").addEventListener("click", () => zoomMap(0.8));
byId("map-fit").addEventListener("click", fitMap);
byId("map-center-robot").addEventListener("click", () => centerRobot());
byId("map-follow").addEventListener("change", () => requestMapDraw());
byId("map-initial-pose").addEventListener("click", () => {
  mapView.poseMode = !mapView.poseMode;
  mapView.poseDraft = null;
  mapView.posePointerId = null;
  mapView.dragging = false;
  byId("map-follow").checked = false;
  byId("map-canvas").classList.toggle("pose-mode", mapView.poseMode);
  toast(mapView.poseMode ? "Toca el mapa y arrastra la orientacion" : "Reubicacion cancelada");
  renderState();
});

byId("map-canvas").addEventListener("wheel", (event) => {
  event.preventDefault();
  const rect = byId("map-canvas").getBoundingClientRect();
  zoomMap(Math.exp(-event.deltaY * 0.0012), event.clientX - rect.left, event.clientY - rect.top);
}, {passive: false});

byId("map-canvas").addEventListener("pointerdown", (event) => {
  if (mapView.poseMode) {
    event.preventDefault();
    const rect = byId("map-canvas").getBoundingClientRect();
    const world = canvasToWorld(event.clientX - rect.left, event.clientY - rect.top);
    mapView.poseDraft = {...world, yaw: dashboardState.robot_pose?.yaw || 0};
    mapView.posePointerId = event.pointerId;
    byId("map-canvas").setPointerCapture(event.pointerId);
    requestMapDraw();
    return;
  }

  mapView.dragging = true;
  mapView.pointerX = event.clientX;
  mapView.pointerY = event.clientY;
  byId("map-follow").checked = false;
  byId("map-canvas").classList.add("dragging");
  byId("map-canvas").setPointerCapture(event.pointerId);
});

byId("map-canvas").addEventListener("pointermove", (event) => {
  if (mapView.poseMode && mapView.poseDraft && event.pointerId === mapView.posePointerId) {
    event.preventDefault();
    const rect = byId("map-canvas").getBoundingClientRect();
    const world = canvasToWorld(event.clientX - rect.left, event.clientY - rect.top);
    const dx = world.x - mapView.poseDraft.x;
    const dy = world.y - mapView.poseDraft.y;
    if (Math.hypot(dx, dy) > 0.02) mapView.poseDraft.yaw = Math.atan2(dy, dx);
    requestMapDraw();
    return;
  }

  if (!mapView.dragging) return;
  mapView.offsetX += event.clientX - mapView.pointerX;
  mapView.offsetY += event.clientY - mapView.pointerY;
  mapView.pointerX = event.clientX;
  mapView.pointerY = event.clientY;
  requestMapDraw();
});

function finishMapDrag(event) {
  if (mapView.poseMode) {
    const draft = mapView.poseDraft;
    if (event.pointerId !== undefined && byId("map-canvas").hasPointerCapture(event.pointerId)) {
      byId("map-canvas").releasePointerCapture(event.pointerId);
    }
    if (event.type === "pointercancel") {
      mapView.poseDraft = null;
      mapView.posePointerId = null;
      requestMapDraw();
      return;
    }
    if (draft && event.pointerId === mapView.posePointerId) {
      sendInitialPose(draft).then((sent) => {
        if (sent) {
          mapView.poseMode = false;
          byId("map-canvas").classList.remove("pose-mode");
        }
        mapView.poseDraft = null;
        mapView.posePointerId = null;
        renderState();
      });
    }
    return;
  }

  mapView.dragging = false;
  byId("map-canvas").classList.remove("dragging");
  if (event.pointerId !== undefined && byId("map-canvas").hasPointerCapture(event.pointerId)) {
    byId("map-canvas").releasePointerCapture(event.pointerId);
  }
}

byId("map-canvas").addEventListener("pointerup", finishMapDrag);
byId("map-canvas").addEventListener("pointercancel", finishMapDrag);

new ResizeObserver(() => {
  if (byId("view-carolina").classList.contains("active")) requestMapDraw();
}).observe(byId("map-stage"));

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
byId("terminal-clear").addEventListener("click", () => {
  terminal?.clear();
  byId("terminal-fallback").textContent = "";
});
byId("terminal-keyboard").addEventListener("click", () => {
  if (isAppleTouchDevice() || terminalFallbackActive) byId("terminal-command-input").focus();
  else terminal?.focus();
});
byId("terminal-command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = byId("terminal-command-input");
  if (!input.value || !sendTerminalInput(`${input.value}\r`)) return;
  input.value = "";
  input.focus();
});
byId("terminal-interrupt").addEventListener("click", () => {
  sendTerminalInput("\x03");
  byId("terminal-command-input").focus();
});
byId("terminal-fullscreen").addEventListener("click", async () => {
  const stage = byId("terminal-stage");
  if (document.fullscreenElement && document.exitFullscreen) await document.exitFullscreen();
  else if (stage.requestFullscreen) await stage.requestFullscreen();
  else if (isAppleTouchDevice() || terminalFallbackActive) byId("terminal-command-input").focus();
  else terminal?.focus();
  window.setTimeout(fitTerminal, 80);
});

window.addEventListener("online", () => {
  connectStateSocket();
  if (terminalStarted && byId("view-terminal").classList.contains("active")) connectTerminal();
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  connectStateSocket();
  if (terminalStarted && byId("view-terminal").classList.contains("active")) connectTerminal();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !byId("confirm-modal").hidden) closeConfirm(false);
  if (event.key === "Escape" && !byId("logs-modal").hidden) byId("logs-modal").hidden = true;
  if (event.key === "Escape" && mapView.poseMode) {
    mapView.poseMode = false;
    mapView.poseDraft = null;
    mapView.posePointerId = null;
    byId("map-canvas").classList.remove("pose-mode");
    renderState();
  }
});

window.setInterval(() => {
  text("local-clock", new Date().toLocaleTimeString("es-VE", {hour12: false}));
  renderState();
}, 1000);

if (window.lucide) window.lucide.createIcons();
renderState();
renderEvents();
connectStateSocket();
loadAvailableRoutes();
loadNavigationMaps();
loadEvaluation();
const requestedView = location.hash.slice(1);
const initialView = requestedView === "map"
  ? "carolina"
  : ["dashboard", "carolina", "isa", "vision", "evaluation", "terminal", "events"].includes(requestedView)
    ? requestedView
    : "dashboard";
switchView(initialView);
