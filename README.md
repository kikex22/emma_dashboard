# EMMA Dashboard V1

Estacion local de operacion para Carolina Patrol e ISA. La pagina y el puente
ROS se ejecutan en la PC; el robot conserva sus nodos y expone telemetria por
ROS 2.

## Preparacion

```bash
cd /home/adjor/Emma/src/emma_dashboard
./setup.sh
```

## Ejecucion

```bash
./run.sh
```

Abrir `http://127.0.0.1:8765`.

## Configuracion opcional

- `EMMA_ORIN_HOST`: IP del Orin. Predeterminado: `192.168.68.72`.
- `EMMA_ORIN_USER`: usuario SSH. Predeterminado: `jetson`.
- `EMMA_ORIN_KEY`: llave SSH. Predeterminado: `/home/adjor/.ssh/orion`.
- `EMMA_DASHBOARD_PORT`: puerto web. Predeterminado: `8765`.
- `ROS_DOMAIN_ID`: dominio ROS 2. Predeterminado: `99`.

El servidor escucha solamente en `127.0.0.1` de forma predeterminada. La llave
SSH se usa en el backend y nunca se envia al navegador.
