# Auditoria backend LabConnect (PocketBase-only)

Fecha: 2026-04-08

## 1. Resumen ejecutivo

Se reviso el backend completo y se identifico una arquitectura de microservicios con PocketBase como fuente principal de datos, pero con rutas de fallback/sombra a PostgreSQL en parte del codigo.

Para dejar el despliegue en modo PocketBase-only, ya se aplicaron estos cambios:

- Se elimino el servicio `postgres` de `docker-compose.yml`.
- Se eliminaron `POSTGRES_URL` y dependencias `depends_on: postgres` de servicios activos.
- Se cambio el `DATA_MODE` por defecto a `pocketbase` en los servicios que lo usan.

Con esto, el arranque ya no crea ni levanta PostgreSQL desde Compose y el modo operativo por defecto queda orientado a PocketBase.

## 2. Colecciones PocketBase que debes tener

## 2.1 Colecciones core (obligatorias)

- `users`
- `role`
- `area`
- `laboratory`
- `asset`
- `stock_item`
- `lab_reservation`
- `lab_schedule`
- `lab_block`
- `lab_access_sessions_v2`
- `supply_reservation`

## 2.2 Colecciones de inventario avanzado (obligatorias si usas prestamos/mantenimiento)

- `inventory_loan_records_v2`
- `inventory_asset_maintenance_tickets_v2`

## 2.3 Colecciones de sync/legacy (recomendadas por compatibilidad)

- `inventory_assets_v2`
- `inventory_stock_items_v2`
- `inventory_stock_movements_v2`
- `inventory_asset_status_logs_v2`

Notas:

- Algunos repositorios de inventario trabajan con colecciones cortas (`asset`, `stock_item`), mientras que parte del codigo de sincronizacion usa sufijo `_v2`.
- Mantener ambas familias evita roturas mientras se unifica el modelo.

## 2.4 Coleccion de autenticacion PocketBase

- `_superusers` (sistema PocketBase) para auth admin de servicios.

## 3. Servicios conectados a PocketBase y no conectados

## 3.1 Conectados directamente a PocketBase

- `auth-service`
- `role-service`
- `inventory-service`
- `reservation-service`
- `supply-reservation-service` (en codigo)

## 3.2 No conectados directamente a PocketBase

- `api-gateway` (solo proxy HTTP entre frontend y microservicios)
- `mailpit` (SMTP de pruebas)

## 3.3 Importante de despliegue

- `supply-reservation-service` existe en codigo y usa PocketBase, pero no esta declarado en el `docker-compose.yml` actual.

## 4. Cambios aplicados para quitar creacion/uso de Postgres en despliegue

Se aplicaron estos cambios de codigo/config:

- `docker-compose.yml`
  - eliminado servicio `postgres`
  - eliminadas variables `POSTGRES_URL` de servicios
  - eliminado `depends_on` hacia postgres
  - `DATA_MODE` por defecto cambiado a `pocketbase`
- `auth-service/app/core/config.py`
  - `DATA_MODE` default: `hybrid` -> `pocketbase`
- `role-service/app/core/config.py`
  - `DATA_MODE` default: `hybrid` -> `pocketbase`
- `inventory-service/app/core/config.py`
  - `DATA_MODE` default: `hybrid` -> `pocketbase`
- `reservation-service/app/core/config.py`
  - `DATA_MODE` default: `hybrid` -> `pocketbase`

Resultado practico:

- Ya no se crea ni inicia PostgreSQL desde la orquestacion principal.
- El backend arranca por defecto en modo PocketBase.

## 5. Lo que tienes que saber de este backend

## 5.1 Arquitectura actual

- Patrón de microservicios FastAPI.
- `api-gateway` enruta rutas REST a auth, role, inventory y reservation.
- Seguridad con JWT y validaciones cruzadas entre servicios.

## 5.2 Flujo funcional alto nivel

- `auth-service`: login/registro/usuarios.
- `role-service`: catalogo de roles/permisos y asignaciones.
- `inventory-service`: areas, laboratorios, activos, insumos, prestamos, mantenimiento.
- `reservation-service`: horarios, reservas, bloqueos, sesiones de acceso, tutoriales, recordatorios, penalizaciones.
- `supply-reservation-service`: reservas de insumos y ajuste de stock.

## 5.3 Riesgos tecnicos detectados

- Coexisten nombres de colecciones legacy y `_v2` en inventario.
- Aun existe codigo de fallback local/sombra a Postgres en el repositorio (no activo por defecto tras los cambios), lo que agrega complejidad de mantenimiento.
- `README.md` principal esta desactualizado respecto a la arquitectura real.

## 5.4 Recomendaciones para estabilizar PocketBase-only

- Unificar nombres de colecciones (quedarte con una sola familia, idealmente `_v2` o la corta, no ambas).
- Retirar en una segunda pasada el codigo fallback/sombra a Postgres que ya no se use.
- Agregar `supply-reservation-service` al compose si debe operar en el entorno principal.
- Actualizar `README.md` con arquitectura real, puertos, variables y colecciones.

## 6. Variables de entorno clave para PocketBase-only

Minimas:

- `POCKETBASE_URL`
- `POCKETBASE_AUTH_IDENTITY`
- `POCKETBASE_AUTH_PASSWORD`
- `POCKETBASE_TIMEOUT_SECONDS`
- `DATA_MODE=pocketbase`

Recomendadas:

- `POCKETBASE_RETRY_SECONDS`
- `POCKETBASE_USERS_COLLECTION=users`
- Colecciones explicitas por dominio (roles, reservas, inventario, supply)

## 7. Checklist rapido de verificacion

- `docker compose config` valido.
- Levantar servicios sin contenedor `postgres`.
- Verificar health endpoints:
  - `/health` de `auth-service`
  - `/health` de `role-service`
  - `/health` de `inventory-service`
  - `/health` de `reservation-service`
  - `/health` de `api-gateway`
- Probar login y una lectura simple por cada dominio (roles, inventario, reservas).
- Confirmar que las colecciones listadas existen en PocketBase.

## 8. Conclusiones

Tu backend ya puede operar en modo PocketBase-only por defecto con los cambios aplicados. La siguiente mejora recomendada es limpiar definitivamente el codigo legacy de Postgres y unificar el esquema de colecciones para reducir complejidad y deuda tecnica.
