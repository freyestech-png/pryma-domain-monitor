# PRYMA Domain Monitor

Monitor de solo lectura de `pryma.cl`. Python 3.10+, biblioteca estándar, sin
claves, compras de dominios ni servicios contratados.

## Estado

**Validado desde GitHub Actions el 14 de noviembre de 2026, 01:22:40 de Chile.**
HTTP y WHOIS directo coincidieron: `pryma.cl` está **en eliminación**, no disponible.
Las 36 pruebas pasaron y el historial se guardó correctamente en GitHub.
[Ejecución y registros](https://github.com/freyestech-png/pryma-domain-monitor/actions/runs/43556337485).

| Método | Resultado | Tiempo | Respuesta |
|---|---|---:|---:|
| HTTPS GET, URL exacta de NIC | HTTP 200, `en_eliminacion` | 634 ms | 13.866 bytes |
| WHOIS directo, `whois.nic.cl:43` | `en_eliminacion` | 480 ms | 390 bytes |

**Vigilancia habilitada mediante HTTP.** En la segunda comparación desde Actions
(14 de noviembre, 01:46:56 de Chile), HTTP volvió a responder 200; WHOIS directo
falló con `OSError` de transporte. Por eso se seleccionó HTTP como método principal.
WHOIS queda para diagnóstico manual. Estas mediciones no constituyen una garantía
de disponibilidad del servicio.
El fallo DNS local previo (`validation-local.json`) no se reprodujo en Actions.
El estado actual y su antigüedad se consultan en `state/latest.json`; esta sección
documenta la validación inicial, no una cotización ni una reserva de dominio.

## Ejecutar

```bash
python3 -m unittest -v test_monitor test_notify
python3 monitor.py --mode compare
python3 monitor.py --mode http
```

`compare` consulta una vez por HTTP y otra por WHOIS directo (`whois.nic.cl:43`).
La vigilancia usa sólo el método validado. Una restricción explícita pausa
las consultas; no se cambia de transporte para eludirla.

| Estado | Significado |
|---|---|
| `disponible` | NIC dice explícitamente que el dominio no está registrado. Confirmar manualmente: no es reserva ni garantía de compra. |
| `registrado` | Ficha de inscripción del dominio exacto. |
| `en_eliminacion` | Indicación explícita de eliminación o restauración. No es disponibilidad. |
| `error_consulta` | Fallo de red, HTTP, bloqueo, formato desconocido o contradicción. |

Se utiliza la tabla del dominio exacto. Los formularios, scripts y CAPTCHA
ocultos de búsquedas parciales se ignoran. Si los métodos discrepan sobre
disponibilidad, se registra error. No se infiere disponibilidad por DNS ni por
fecha de vencimiento. Un resultado vacío nunca significa disponible.

## Historial y límites

- `state/history/AAAA-MM.jsonl`: cada consulta efectiva.
- `state/latest.json`: última consulta con hora UTC y Chile, y cambio de estado.
- `state/control.json`: espera mínima, pausas y último resultado válido con fecha.
- Resumen y logs de Actions: consulta o motivo de omisión.
- Se guardan código HTTP, tamaño y hash; no titulares, correos, cookies ni HTML completo.
- Mínimo 900 segundos entre consultas usando el mismo estado persistente.
- Errores: espera de 30, 60, 120 minutos, etc., hasta 24 horas. Un `Retry-After` mayor prevalece.
- HTTP 401/403/429 o desafío explícito: pausa persistente para revisión manual.
- Estado corrupto: se detiene antes de consultar. No se borra el historial.
- Sin reintentos de NIC dentro del mismo trabajo.
- `state/notifications.json`: cursor de avisos enviados, sin correos ni credenciales.

La política de NIC revisada no establece una cuota numérica. Cuatro consultas
por hora es una propuesta conservadora, no un límite oficialmente garantizado.
Se respetarán las restricciones que comunique el servicio.

## GitHub Actions y costo

Repositorio público autorizado por su propietario. Código y resultados son
visibles. Se usa sólo el runner estándar `ubuntu-24.04`, gratuito para repositorios
públicos. Sin runners de pago, artifacts ni cachés. No requiere contratar un
plan o servidor. Sujeto a las condiciones de GitHub.

El workflow ejecuta pruebas, consulta y guarda el historial en commits de `main`.
Si guardar falla, el trabajo falla: revisar logs antes de activar recurrencia.
Los commits del historial no disparan una nueva consulta por `push`.

Cron habilitado: `7,22,37,52 * * * *` (UTC), cada 15 minutos. Variables de
Actions configuradas: `MONITOR_ENABLED=true` y `MONITOR_METHOD=http`.
Para detenerlo, cambiar `MONITOR_ENABLED` a `false` en Settings → Secrets and
variables → Actions → Variables. Todas las ejecuciones quedan bloqueadas
si el repositorio pasa a privado, para evitar costos no autorizados.

GitHub puede retrasar u omitir ejecuciones y desactivar schedules públicos tras
60 días sin actividad. La espera mínima puede omitir una ejecución que llegue
demasiado pronto respecto de la anterior. No se garantiza un intervalo exacto.
No ejecutar copias paralelas con estados independientes.

Un error de consulta nunca se presenta como disponibilidad. Ante una
pausa por restricciones, revisar los logs y las condiciones de NIC antes de
reanudar; no cambiar de método ni borrar el estado para eludir el bloqueo.

## Avisos gratuitos

**Avisos activados y entrega de correo verificada el 14 de noviembre de 2026,
01:47 de Chile.** Las 46 pruebas pasaron también en
[GitHub Actions](https://github.com/freyestech-png/pryma-domain-monitor/actions/runs/43558325542).
La [prueba de aviso](https://github.com/freyestech-png/pryma-domain-monitor/issues/1)
llegó al buzón del propietario. No anunció disponibilidad: el estado era en eliminación.

`notify.py` crea una incidencia de GitHub por cada cambio de estado y menciona
al propietario `freyestech-png`. GitHub envía el contenido por correo
si están habilitadas las notificaciones de participación y menciones.
El correo de destino se administra en las preferencias privadas de GitHub;
no se incluye en los archivos ni en los avisos del monitor. GitHub Mobile permite añadir
avisos push para menciones y asignaciones en el teléfono.

- Al instalarlo, se envía una **PRUEBA DE AVISO** con el estado real observado.
- Si NIC indica disponibilidad, el asunto será **PRYMA.CL DISPONIBLE — revisar e inscribir en NIC Chile**.
- El aviso incluye estado anterior/nuevo, hora de Chile, consulta completa del monitor y enlaces a NIC y al registro de ejecución.
- Las consultas sin cambios no generan correo. Los errores y su recuperación se distinguen de la disponibilidad.
- Un envío fallido queda pendiente. Se busca una marca única en GitHub antes de repetirlo para evitar duplicados, incluso si se pierde la respuesta tras crear la incidencia.
- Se procesan las transiciones pendientes del historial, incluida una disponibilidad breve seguida de otro estado; verificar siempre la hora del aviso.
- Usa sólo el token temporal incorporado en Actions (`issues: write`). No hay claves de correo, servidores SMTP ni servicios contratados.
- 46 pruebas aprobadas localmente y en Actions: 36 del monitor y 10 sobre alertas, fallos, duplicados y transiciones.
- La prueba inicial generó dos correos (mención y asignación); se eliminó la asignación automática para evitar ese aviso adicional.
- Una prueba adicional usa una respuesta HTTP real de un dominio de control no registrado. Verifica el formato de disponibilidad y rechaza atribuir el resultado de otro dominio a `pryma.cl` (47 pruebas en total). No fue una observación de disponibilidad de `pryma.cl`.

Crear la incidencia confirma la entrega a GitHub, no la llegada al buzón.
Revisar la prueba de correo (incluido spam) para validar la entrega final.
El objetivo es avisar al detectar disponibilidad; la programación, NIC y la
entrega de correo pueden retrasarse. No se reserva ni se compra el dominio.

## Fuentes

- [Consulta exacta NIC](https://www.nic.cl/registry/Whois.do?d=pryma.cl)
- [Servidor WHOIS oficial de .cl](https://www.iana.org/domains/root/db/cl.html)
- [Política de publicación NIC](https://www.nic.cl/normativa/politica-publicacion-de-datos-cl.pdf)
- [GitHub: facturación](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub: schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [GitHub: configurar correo y avisos móviles](https://docs.github.com/es/subscriptions-and-notifications/get-started/configuring-notifications)
