#!/usr/bin/env python3
from pathlib import Path
import re
import shutil

ROOT = Path.cwd()
STATIC = ROOT / "emma_dashboard" / "static"
HTML = STATIC / "index.html"
CSS = STATIC / "app.css"
JS = STATIC / "app.js"

for p in (HTML, CSS, JS):
    if not p.is_file():
        raise SystemExit(
            f"ERROR: no encuentro {p}\n"
            "Ejecuta este instalador desde ~/emma/src/emma_dashboard"
        )

def backup(p: Path):
    b = p.with_name(p.name + ".before-v1.2")
    if not b.exists():
        shutil.copy2(p, b)

def sub_one(pattern, repl, text, label, flags=0):
    new, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"ERROR [{label}]: esperaba 1 coincidencia y encontre {count}.")
    return new

for p in (HTML, CSS, JS):
    backup(p)

html = HTML.read_text(encoding="utf-8")

# Visible version + browser cache busting.
html = re.sub(r'ORIN / OPERATIONS V1\.1', 'ORIN / OPERATIONS V1.2', html, count=1)
html = re.sub(r'/static/app\.css\?v=[^"]+', '/static/app.css?v=1.2', html, count=1)
html = re.sub(r'/static/app\.js\?v=[^"]+', '/static/app.js?v=1.2', html, count=1)

# Mapa tab -> Carolina.
html = sub_one(
    r'<button class="tab-button" data-view-target="map" role="tab" aria-selected="false">\s*'
    r'<i data-lucide="map"></i><span>Mapa</span>\s*</button>',
    '''<button class="tab-button" data-view-target="carolina" role="tab" aria-selected="false">
            <i data-lucide="route"></i><span>Carolina</span>
          </button>''',
    html,
    "tab Carolina",
    flags=re.S,
)

# Remove the old Patrol card from Dashboard.
html = sub_one(
    r'\s*<article class="ops-panel patrol-panel">.*?<h2>Carolina Patrol</h2>.*?</article>',
    '',
    html,
    "Patrol card del Dashboard",
    flags=re.S,
)

# Remove the old Patrol Setup card from Dashboard.
html = sub_one(
    r'\s*<aside class="ops-panel control-panel">.*?<h2>Patrol Setup</h2>.*?</aside>',
    '',
    html,
    "Patrol Setup del Dashboard",
    flags=re.S,
)

carolina_section = '''
        <section class="view map-view carolina-view" id="view-carolina" aria-label="Carolina Patrol">
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
                  <button class="command-button positive" data-subsystem="patrol" data-command="start">
                    <i data-lucide="play"></i><span>Start</span>
                  </button>
                  <button class="command-button danger" data-subsystem="patrol" data-command="hold">
                    <i data-lucide="octagon-pause"></i><span>Hold</span>
                  </button>
                  <button class="command-button" data-subsystem="patrol" data-command="resume">
                    <i data-lucide="step-forward"></i><span>Resume</span>
                  </button>
                  <button class="icon-button" title="Recargar ruta" aria-label="Recargar ruta"
                          data-subsystem="patrol" data-command="reload"
                          data-confirm="Recargar la ruta activa de Carolina?">
                    <i data-lucide="refresh-cw"></i>
                  </button>
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
              </section>
            </aside>
          </div>
        </section>
'''

html = sub_one(
    r'\s*<section class="view map-view" id="view-map" aria-label="Mapa de navegacion">.*?'
    r'(?=\s*<section class="view isa-ops-view" id="view-isa")',
    '\n' + carolina_section + '\n',
    html,
    "vista Mapa -> Carolina",
    flags=re.S,
)

HTML.write_text(html, encoding="utf-8")

js = JS.read_text(encoding="utf-8")

js = sub_one(
    r'if \(viewName === "map"\) window\.setTimeout\(requestMapDraw, 40\);',
    'if (viewName === "carolina") window.setTimeout(requestMapDraw, 40);',
    js,
    "switchView Carolina",
)

js = sub_one(
    r'if \(byId\("view-map"\)\.classList\.contains\("active"\)\) requestMapDraw\(\);',
    'if (byId("view-carolina").classList.contains("active")) requestMapDraw();',
    js,
    "ResizeObserver Carolina",
)

js = sub_one(
    r'const initialView = \["dashboard", "map", "isa", "vision", "terminal", "events"\]\.includes\(location\.hash\.slice\(1\)\)\s*'
    r'\? location\.hash\.slice\(1\)\s*'
    r': "dashboard";',
    '''const requestedView = location.hash.slice(1);
const initialView = requestedView === "map"
  ? "carolina"
  : ["dashboard", "carolina", "isa", "vision", "terminal", "events"].includes(requestedView)
    ? requestedView
    : "dashboard";''',
    js,
    "initialView Carolina",
    flags=re.S,
)

JS.write_text(js, encoding="utf-8")

css = CSS.read_text(encoding="utf-8")
if "/* ===== V1.2 / Carolina ===== */" not in css:
    css += '''

/* ===== V1.2 / Carolina ===== */
.carolina-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 370px);
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

  .carolina-primary-controls {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .carolina-primary-controls .icon-button {
    width: 100%;
    grid-column: 1 / -1;
  }
}
'''
    CSS.write_text(css, encoding="utf-8")

print("OK: EMMA Dashboard V1.2 / Carolina aplicado.")
print("Backups:")
print("  emma_dashboard/static/index.html.before-v1.2")
print("  emma_dashboard/static/app.js.before-v1.2")
print("  emma_dashboard/static/app.css.before-v1.2")
