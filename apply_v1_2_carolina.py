#!/usr/bin/env python3
from pathlib import Path
import shutil

ROOT = Path.cwd()
HTML = ROOT / "emma_dashboard" / "static" / "index.html"
CSS = ROOT / "emma_dashboard" / "static" / "app.css"
JS = ROOT / "emma_dashboard" / "static" / "app.js"

for path in (HTML, CSS, JS):
    if not path.is_file():
        raise SystemExit(f"ERROR: no encuentro {path}. Ejecuta este script desde la raiz de emma_dashboard.")

def backup(path: Path) -> None:
    backup_path = path.with_name(path.name + ".v1.1.backup")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"ERROR [{label}]: esperaba 1 coincidencia y encontre {count}.")
    return text.replace(old, new, 1)

backup(HTML)
html = HTML.read_text(encoding="utf-8")

html = replace_once(
    html,
    '<link rel="stylesheet" href="/static/app.css?v=20260915-isa3">',
    '<link rel="stylesheet" href="/static/app.css?v=1.2">',
    "css cache",
)

html = replace_once(
    html,
    '<span>ORIN / OPERATIONS V1.1</span>',
    '<span>ORIN / OPERATIONS V1.2</span>',
    "version",
)

html = replace_once(
    html,
    '''          <button class="tab-button" data-view-target="map" role="tab" aria-selected="false">
            <i data-lucide="map"></i><span>Mapa</span>
          </button>''',
    '''          <button class="tab-button" data-view-target="carolina" role="tab" aria-selected="false">
            <i data-lucide="route"></i><span>Carolina</span>
          </button>''',
    "carolina tab",
)

dashboard_patrol = '''            <article class="ops-panel patrol-panel">
              <header class="panel-header">
                <div>
                  <span class="panel-kicker">NAVIGATION</span>
                  <h2>Carolina Patrol</h2>
                </div>
                <span class="module-state" id="patrol-online" data-state="offline">
                  <span class="status-dot"></span>OFFLINE
                </span>
              </header>
              <dl class="telemetry-list">
                <div><dt>Estado</dt><dd id="patrol-status">sin datos</dd></div>
                <div><dt>Ruta activa</dt><dd id="patrol-route">--</dd></div>
                <div><dt>Waypoint</dt><dd id="patrol-waypoint">--</dd></div>
                <div><dt>Velocidad</dt><dd id="patrol-speed">--</dd></div>
                <div><dt>Odometria</dt><dd id="patrol-odom">--</dd></div>
                <div><dt>Control base</dt><dd id="patrol-owner">--</dd></div>
              </dl>
              <div class="command-row primary-controls">
                <button class="command-button positive" data-subsystem="patrol" data-command="start">
                  <i data-lucide="play"></i><span>Start</span>
                </button>
                <button class="command-button danger" data-subsystem="patrol" data-command="hold">
                  <i data-lucide="octagon-pause"></i><span>Hold</span>
                </button>
                <button class="command-button" data-subsystem="patrol" data-command="resume">
                  <i data-lucide="step-forward"></i><span>Resume</span>
                </button>
                <button class="icon-button" title="Recargar ruta" aria-label="Recargar ruta" data-subsystem="patrol" data-command="reload" data-confirm="Recargar la ruta activa de Carolina?">
                  <i data-lucide="refresh-cw"></i>
                </button>
              </div>
            </article>
'''

html = replace_once(html, dashboard_patrol, "", "remove dashboard patrol")

dashboard_setup = '''            <aside class="ops-panel control-panel">
              <header class="panel-header compact">
                <div>
                  <span class="panel-kicker green">MISSION SETUP</span>
                  <h2>Patrol Setup</h2>
                </div>
              </header>

              <label class="field-control">
                <span>Ruta</span>
                <select id="route-select">
                  <option value="route_1">route_1</option>
                  <option value="route_2">route_2</option>
                  <option value="route_3">route_3</option>
                </select>
              </label>
              <button class="wide-button" id="apply-route">
                <i data-lucide="route"></i><span>Seleccionar ruta</span>
              </button>

              <label class="field-control">
                <span>Perfil de velocidad</span>
                <select id="speed-select">
                  <option value="slow_linear">slow_linear</option>
                  <option value="normal_linear">normal_linear</option>
                  <option value="fast_linear">fast_linear</option>
                  <option value="slow_omni">slow_omni</option>
                  <option value="normal_omni" selected>normal_omni</option>
                  <option value="fast_omni">fast_omni</option>
                </select>
              </label>
              <button class="wide-button" id="apply-speed">
                <i data-lucide="gauge"></i><span>Aplicar perfil</span>
              </button>

              <div class="base-state">
                <span>BASE CONTROL</span>
                <strong id="base-state">sin datos</strong>
                <small id="base-estop">E-STOP --</small>
              </div>
            </aside>
'''

html = replace_once(html, dashboard_setup, "", "remove dashboard patrol setup")

old_map = '''        <section class="view map-view" id="view-map" aria-label="Mapa de navegacion">
          <div class="map-toolbar">
            <div class="map-identity">
              <i data-lucide="map"></i>
              <div><strong>Mapa de navegación</strong><span id="map-frame">FRAME --</span></div>
            </div>
            <span class="module-state" id="map-status" data-state="offline">
              <span class="status-dot"></span>SIN MAPA
            </span>
            <div class="map-controls">
              <button class="icon-button" id="map-zoom-out" title="Alejar" aria-label="Alejar"><i data-lucide="zoom-out"></i></button>
              <button class="icon-button" id="map-zoom-in" title="Acercar" aria-label="Acercar"><i data-lucide="zoom-in"></i></button>
              <button class="icon-button" id="map-fit" title="Ajustar mapa" aria-label="Ajustar mapa"><i data-lucide="scan"></i></button>
              <button class="icon-button" id="map-center-robot" title="Centrar robot" aria-label="Centrar robot"><i data-lucide="crosshair"></i></button>
              <button class="icon-button pose-button" id="map-initial-pose" title="Reubicar robot" aria-label="Reubicar robot"><i data-lucide="map-pin-plus"></i></button>
              <label class="follow-control">
                <input type="checkbox" id="map-follow">
                <span>Seguir robot</span>
              </label>
            </div>
          </div>
          <div class="map-stage" id="map-stage">
            <canvas id="map-canvas" aria-label="Mapa 2D de EMMA"></canvas>
            <div class="map-empty" id="map-empty">ESPERANDO /MAP</div>
            <div class="map-hud">
              <div><span>ROBOT</span><strong id="map-robot-pose">SIN TF</strong></div>
              <div><span>RUTA</span><strong id="map-route-status">SIN PUNTOS</strong></div>
              <div><span>POSE</span><strong id="map-pose-mode">NORMAL</strong></div>
              <div><span>ESCALA</span><strong id="map-scale">--</strong></div>
            </div>
          </div>
        </section>'''

new_carolina = '''        <section class="view map-view carolina-view" id="view-carolina" aria-label="Carolina Patrol">
          <div class="map-toolbar">
            <div class="map-identity">
              <i data-lucide="route"></i>
              <div><strong>Carolina</strong><span id="map-frame">NAVIGATION / FRAME --</span></div>
            </div>
            <span class="module-state" id="map-status" data-state="offline">
              <span class="status-dot"></span>SIN MAPA
            </span>
            <div class="map-controls">
              <button class="icon-button" id="map-zoom-out" title="Alejar" aria-label="Alejar"><i data-lucide="zoom-out"></i></button>
              <button class="icon-button" id="map-zoom-in" title="Acercar" aria-label="Acercar"><i data-lucide="zoom-in"></i></button>
              <button class="icon-button" id="map-fit" title="Ajustar mapa" aria-label="Ajustar mapa"><i data-lucide="scan"></i></button>
              <button class="icon-button" id="map-center-robot" title="Centrar robot" aria-label="Centrar robot"><i data-lucide="crosshair"></i></button>
              <button class="icon-button pose-button" id="map-initial-pose" title="Reubicar robot" aria-label="Reubicar robot"><i data-lucide="map-pin-plus"></i></button>
              <label class="follow-control">
                <input type="checkbox" id="map-follow">
                <span>Seguir robot</span>
              </label>
            </div>
          </div>

          <div class="carolina-workspace">
            <div class="map-stage" id="map-stage">
              <canvas id="map-canvas" aria-label="Mapa 2D de EMMA"></canvas>
              <div class="map-empty" id="map-empty">ESPERANDO /MAP</div>
              <div class="map-hud">
                <div><span>ROBOT</span><strong id="map-robot-pose">SIN TF</strong></div>
                <div><span>RUTA</span><strong id="map-route-status">SIN PUNTOS</strong></div>
                <div><span>POSE</span><strong id="map-pose-mode">NORMAL</strong></div>
                <div><span>ESCALA</span><strong id="map-scale">--</strong></div>
              </div>
            </div>

            <aside class="carolina-sidebar">
              <section class="ops-panel patrol-panel carolina-patrol-panel">
                <header class="panel-header">
                  <div>
                    <span class="panel-kicker">PATROL</span>
                    <h2>Carolina Patrol</h2>
                  </div>
                  <span class="module-state" id="patrol-online" data-state="offline">
                    <span class="status-dot"></span>OFFLINE
                  </span>
                </header>
                <dl class="telemetry-list">
                  <div><dt>Estado</dt><dd id="patrol-status">sin datos</dd></div>
                  <div><dt>Ruta activa</dt><dd id="patrol-route">--</dd></div>
                  <div><dt>Waypoint</dt><dd id="patrol-waypoint">--</dd></div>
                  <div><dt>Velocidad</dt><dd id="patrol-speed">--</dd></div>
                  <div><dt>Odometria</dt><dd id="patrol-odom">--</dd></div>
                  <div><dt>Control base</dt><dd id="patrol-owner">--</dd></div>
                </dl>
                <div class="command-row primary-controls carolina-primary-controls">
                  <button class="command-button positive" data-subsystem="patrol" data-command="start"><i data-lucide="play"></i><span>Start</span></button>
                  <button class="command-button danger" data-subsystem="patrol" data-command="hold"><i data-lucide="octagon-pause"></i><span>Hold</span></button>
                  <button class="command-button" data-subsystem="patrol" data-command="resume"><i data-lucide="step-forward"></i><span>Resume</span></button>
                  <button class="icon-button" title="Recargar ruta" aria-label="Recargar ruta" data-subsystem="patrol" data-command="reload" data-confirm="Recargar la ruta activa de Carolina?"><i data-lucide="refresh-cw"></i></button>
                </div>
              </section>

              <section class="ops-panel control-panel carolina-setup-panel">
                <header class="panel-header compact">
                  <div>
                    <span class="panel-kicker green">MISSION SETUP</span>
                    <h2>Ruta y velocidad</h2>
                  </div>
                </header>
                <label class="field-control">
                  <span>Ruta</span>
                  <select id="route-select">
                    <option value="route_1">route_1</option>
                    <option value="route_2">route_2</option>
                    <option value="route_3">route_3</option>
                  </select>
                </label>
                <button class="wide-button" id="apply-route"><i data-lucide="route"></i><span>Seleccionar ruta</span></button>
                <label class="field-control">
                  <span>Perfil de velocidad</span>
                  <select id="speed-select">
                    <option value="slow_linear">slow_linear</option>
                    <option value="normal_linear">normal_linear</option>
                    <option value="fast_linear">fast_linear</option>
                    <option value="slow_omni">slow_omni</option>
                    <option value="normal_omni" selected>normal_omni</option>
                    <option value="fast_omni">fast_omni</option>
                  </select>
                </label>
                <button class="wide-button" id="apply-speed"><i data-lucide="gauge"></i><span>Aplicar perfil</span></button>
                <div class="base-state">
                  <span>BASE CONTROL</span>
                  <strong id="base-state">sin datos</strong>
                  <small id="base-estop">E-STOP --</small>
                </div>
              </section>
            </aside>
          </div>
        </section>'''

html = replace_once(html, old_map, new_carolina, "map -> carolina")

html = replace_once(
    html,
    '<script src="/static/app.js?v=20260915-isa3"></script>',
    '<script src="/static/app.js?v=1.2"></script>',
    "js cache",
)

HTML.write_text(html, encoding="utf-8")

backup(JS)
js = JS.read_text(encoding="utf-8")
js = replace_once(
    js,
    '  if (viewName === "map") window.setTimeout(requestMapDraw, 40);',
    '  if (viewName === "carolina") window.setTimeout(requestMapDraw, 40);',
    "switchView carolina",
)
js = replace_once(
    js,
    '  if (byId("view-map").classList.contains("active")) requestMapDraw();',
    '  if (byId("view-carolina").classList.contains("active")) requestMapDraw();',
    "map resize observer",
)
old_initial_view = '''const initialView = ["dashboard", "map", "isa", "vision", "terminal", "events"].includes(location.hash.slice(1))
  ? location.hash.slice(1)
  : "dashboard";
switchView(initialView);'''
new_initial_view = '''const requestedView = location.hash.slice(1);
const initialView = requestedView === "map"
  ? "carolina"
  : ["dashboard", "carolina", "isa", "vision", "terminal", "events"].includes(requestedView)
    ? requestedView
    : "dashboard";
switchView(initialView);'''
js = replace_once(js, old_initial_view, new_initial_view, "initial view")
JS.write_text(js, encoding="utf-8")

backup(CSS)
css = CSS.read_text(encoding="utf-8")
if "/* ===== V1.2 / Carolina ===== */" in css:
    raise SystemExit("ERROR: los estilos V1.2 Carolina ya parecen estar aplicados.")

carolina_css = r'''

/* ===== V1.2 / Carolina ===== */

.carolina-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(310px, 360px);
  gap: 14px;
  min-width: 0;
  min-height: 0;
  padding: 14px;
  overflow: hidden;
  background: #080a0c;
}

.carolina-workspace .map-stage {
  border: 1px solid var(--line);
  border-radius: 6px;
}

.carolina-sidebar {
  display: grid;
  grid-auto-rows: max-content;
  align-content: start;
  gap: 14px;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
}

.carolina-sidebar .ops-panel {
  padding: 14px;
}

.carolina-sidebar .panel-header {
  margin-bottom: 14px;
}

.carolina-sidebar .control-panel {
  display: block;
  grid-column: auto;
}

.carolina-sidebar .telemetry-list {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.carolina-primary-controls {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) 38px;
}

.carolina-primary-controls .command-button {
  padding-inline: 8px;
}

@media (max-width: 1050px) {
  .carolina-workspace {
    grid-template-columns: minmax(0, 1fr) 310px;
  }

  .carolina-sidebar .telemetry-list {
    grid-template-columns: minmax(0, 1fr);
  }

  .carolina-sidebar .telemetry-list div:nth-child(even) {
    padding-left: 0;
    border-left: 0;
  }
}

@media (max-width: 820px) {
  .carolina-view.active {
    overflow: auto;
  }

  .carolina-workspace {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(420px, 62vh) auto;
    overflow: visible;
  }

  .carolina-sidebar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    overflow: visible;
  }

  .carolina-sidebar .telemetry-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .carolina-sidebar .telemetry-list div:nth-child(even) {
    padding-left: 14px;
    border-left: 1px solid var(--line);
  }
}

@media (max-width: 620px) {
  .carolina-workspace {
    padding: 8px;
    gap: 8px;
    grid-template-rows: minmax(340px, 56vh) auto;
  }

  .carolina-sidebar {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .carolina-sidebar .telemetry-list {
    grid-template-columns: minmax(0, 1fr);
  }

  .carolina-sidebar .telemetry-list div:nth-child(even) {
    padding-left: 0;
    border-left: 0;
  }

  .carolina-primary-controls {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .carolina-primary-controls .icon-button {
    width: 100%;
    grid-column: 1 / -1;
  }
}
'''

CSS.write_text(css.rstrip() + carolina_css + "\n", encoding="utf-8")

print("V1.2 Carolina aplicado correctamente.")
print("Backups creados con sufijo .v1.1.backup")
