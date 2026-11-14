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

**Vigilancia habilitada mediante WHOIS directo**, más simple y sin dependencia
del formato HTML. HTTP queda para diagnóstico manual. Estas mediciones corresponden
a una ejecución, no constituyen una garantía de disponibilidad del servicio.
El fallo DNS local previo (`validation-local.json`) no se reprodujo en Actions.
El estado actual y su antigüedad se consultan en `state/latest.json`; esta sección
documenta la validación inicial, no una cotización ni una reserva de dominio.

## Ejecutar

```bash
python3 -m unittest -v test_monitor
python3 monitor.py --mode compare
python3 monitor.py --mode whois
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
- Sin reintentos de NIC dentro del mismo trabajo ni avisos por email/Telegram.

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
Actions configuradas: `MONITOR_ENABLED=true` y `MONITOR_METHOD=whois`.
Para detenerlo, cambiar `MONITOR_ENABLED` a `false` en Settings → Secrets and
variables → Actions → Variables. Todas las ejecuciones quedan bloqueadas
si el repositorio pasa a privado, para evitar costos no autorizados.

GitHub puede retrasar u omitir ejecuciones y desactivar schedules públicos tras
60 días sin actividad. La espera mínima puede omitir una ejecución que llegue
demasiado pronto respecto de la anterior. No se garantiza un intervalo exacto.
No ejecutar copias paralelas con estados independientes.

No hay notificaciones de cambio por correo o Telegram: el resultado queda en
GitHub. Un error de consulta nunca se presenta como disponibilidad. Ante una
pausa por restricciones, revisar los logs y las condiciones de NIC antes de
reanudar; no cambiar de método ni borrar el estado para eludir el bloqueo.

## Fuentes

- [Consulta exacta NIC](https://www.nic.cl/registry/Whois.do?d=pryma.cl)
- [Servidor WHOIS oficial de .cl](https://www.iana.org/domains/root/db/cl.html)
- [Política de publicación NIC](https://www.nic.cl/normativa/politica-publicacion-de-datos-cl.pdf)
- [GitHub: facturación](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub: schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
