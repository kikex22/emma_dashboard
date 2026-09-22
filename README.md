# EMMA Dashboard V1.4

Panel de operacion que vive en el Jetson Orin y se conecta directamente a
ROS 2. Incluye controles de Carolina Patrol, terminal local, gestion de Nav2 y
Patrol mediante systemd, un visor 2D alimentado por `/map`, TF y
`/patrol/markers`, dos monitores WebRTC para OD Astra y Arm Cam, y control
interactivo de ISA.

La vista Evaluation integra el recolector de `C26` para los ensayos Carolina
3/4, Vision 5/9 e ISA 8. El recolector se inicia bajo demanda y no enciende ni
controla los modulos operativos que esta observando.

## Preparacion

```bash
cd /home/jetson/emma/src/emma_dashboard
./setup.sh
chmod +x scripts/*.sh
./scripts/install-mediamtx.sh
./scripts/install-systemd.sh
```

Las unidades se instalan sin habilitar arranque automatico.

## Dashboard manual

```bash
systemctl --user start emma-dashboard
systemctl --user status emma-dashboard
systemctl --user stop emma-dashboard
```

Abrir `http://192.168.68.72:8765` desde un equipo en la misma red.

## Procesos del robot

El dashboard controla estas unidades:

```bash
systemctl --user start emma-nav
systemctl --user start emma-patrol
systemctl --user stop emma-patrol
systemctl --user stop emma-nav
systemctl --user start emma-vision.target
systemctl --user stop emma-vision.target
systemctl --user start emma-isa
systemctl --user stop emma-isa
systemctl --user start emma-evaluation
systemctl --user stop emma-evaluation
```

Iniciar Patrol levanta Nav2 si no esta activo. Detener Nav2 tambien detiene
Patrol. Ninguna unidad queda habilitada para iniciar con el Orin.

Vision inicia el gateway WebRTC, Astra Depth y los detectores disponibles. Si
Arm Cam no esta conectada, su unidad permanece inactiva y Astra sigue operando.
Los feeds anotados salen localmente por RTP en `5710` y `5711`; MediaMTX los
expone al navegador en `8889`. El modo dashboard no modifica las variables
`EMMA_VIDEO_HOST`, `EMMA_OD_VIDEO_PORT=5610` ni
`EMMA_ARM_VIDEO_PORT=5611`, que siguen reservadas para PC/laptop.

Iniciar `emma-isa` levanta sus dependencias de Nav2, Patrol y Vision. ISA usa
los detectores locales del Orin y acepta desde el dashboard los mismos comandos
interactivos de la terminal (`a`, `s`, `r`, `c`, `k`, `b`, `t`, `x`, `y`,
`u`, `o`, `g`, `f`, `p`, `h`) mediante `/isa/cmd`. Detener ISA detiene el
orquestador; Nav2, Patrol y Vision conservan sus controles independientes.

`emma-evaluation` ejecuta `evaluation.sh --collector-only`. Normalmente no se
controla a mano: la ventana Evaluation lo inicia al comenzar o recuperar un
ensayo, publica las ordenes en `/evaluation/command` y lo detiene despues de
generar el reporte. Los resultados permanecen en
`~/.emma/evaluation/runs/`.

## Grabaciones

Cada panel de camara permite grabar el video raw, el video anotado o ambos. Los
botones de la barra superior inician y guardan ambas camaras al mismo tiempo.
La grabacion ocurre dentro de los nodos OD y continua aunque se cierre el
navegador.

Los archivos se guardan a 10 FPS con un identificador de sesion compartido:

```text
/home/jetson/Videos/EMMA/astra/YYYY-MM-DD/
/home/jetson/Videos/EMMA/arm/YYYY-MM-DD/
```

`Guardar` finaliza los MP4 activos y `Descartar` elimina solamente la sesion
temporal. Al detener normalmente un detector, cualquier sesion activa se
guarda antes de salir. El detector rechaza nuevas grabaciones cuando quedan
menos de 2 GB libres.

## Logs

```bash
journalctl --user -u emma-nav -f
journalctl --user -u emma-patrol -f
journalctl --user -u emma-dashboard -f
journalctl --user -u emma-video -f
journalctl --user -u emma-od-astra -f
journalctl --user -u emma-od-arm -f
journalctl --user -u emma-isa -f
journalctl --user -u emma-evaluation -f
```

Variables opcionales: `EMMA_DASHBOARD_PORT`, `EMMA_NAV_USE_RVIZ` y
`EMMA_NAV_ENABLE_LIDAR`. Sus valores predeterminados son `8765`, `false` y
`false`.
