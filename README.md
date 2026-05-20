# LabConnect — Backend

Backend de **LabConnect**, sistema de gestión de laboratorios de la UCB. Está compuesto por varios microservicios FastAPI orquestados con Docker Compose y respaldado por **PocketBase** como base de datos.

## Servicios

| Servicio | Puerto (host) | Responsabilidad |
|---|---|---|
| `api-gateway` | `8000` | Punto de entrada único. Proxy HTTP/WebSocket hacia los demás servicios y maneja CORS. |
| `auth-service` | interno `8001` | Login con Google OAuth, emisión y validación de JWT, perfil/directorio de usuarios. |
| `inventory-service` | `8003` | Activos, items de stock, áreas, laboratorios, préstamos y mantenimiento. |
| `role-service` | interno `8004` | Roles y asignación de roles a usuarios. |
| `reservation-service` | `8005` | Reservas de laboratorio, horarios, bloqueos, tutorías, notificaciones, sanciones y realtime (WebSocket). |
| `supply-reservation-service` | `8006` | Reservas de reactivos / insumos. |
| `mailpit` | `1025` SMTP / `8025` UI | Servidor SMTP de desarrollo para correos salientes. |

Todos los servicios FastAPI exponen `GET /health`.

## Almacenamiento

La fuente de verdad es **PocketBase remoto** (URL configurada en `POCKETBASE_URL`). Cada microservicio habla con PocketBase vía HTTP usando credenciales de superusuario. No se utiliza PostgreSQL ni base local.

## Estructura del repo

```
.
├── docker-compose.yml
├── .env
├── api-gateway/
├── auth-service/
├── inventory-service/
├── role-service/
├── reservation-service/
└── supply-reservation-service/
```

Cada servicio sigue el mismo layout:

```
<service>/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py
    ├── core/         # configuración, deps, locks
    ├── api/v1/       # routers FastAPI
    ├── application/  # contenedor de repositorios
    ├── infrastructure/  # clientes PocketBase, repos
    └── schemas/      # modelos Pydantic
```

## Variables de entorno

Configurar en el archivo `.env` en la raíz del repo:

```env
# JWT
SECRET_KEY=<secret aleatorio>
JWT_SECRET=<secret aleatorio>

# URLs públicas
BACKEND_URL=http://localhost:8000
FRONTEND_URLS=http://localhost:5173,http://localhost:3000

# OAuth Google
OAUTH_PROVIDER=google
OAUTH_CLIENT_ID=<google client id>
OAUTH_CLIENT_SECRET=<google client secret>
GOOGLE_CLIENT_ID=<google client id>
GOOGLE_CLIENT_SECRET=<google client secret>

# PocketBase
POCKETBASE_URL=https://<host-pocketbase>
POCKETBASE_AUTH_IDENTITY=<email superusuario>
POCKETBASE_AUTH_PASSWORD=<password superusuario>
POCKETBASE_TIMEOUT_SECONDS=30
```

Variables opcionales útiles: `API_GATEWAY_PORT` (default `8000`), `POCKETBASE_RETRY_SECONDS` (default `60`), `RESERVATION_REMINDER_CHECK_INTERVAL_SECONDS` (default `60`), `SMTP_SENDER` (default `labconnect@ucb.edu.bo`).

## Levantar el stack

```bash
docker compose up --build
```

Servicios accesibles:

- API Gateway: `http://localhost:8000`
- Inventory: `http://localhost:8003`
- Reservation: `http://localhost:8005`
- Supply Reservation: `http://localhost:8006`
- Mailpit UI (correos de prueba): `http://localhost:8025`

Para detener:

```bash
docker compose down
```

## Cómo se enrutan las peticiones

Todo el tráfico cliente pasa por el `api-gateway`. Rutas más relevantes (prefijo `http://localhost:8000`):

| Prefijo público | Servicio destino |
|---|---|
| `/api/auth/*` | auth-service (`/v1/auth/*`) |
| `/api/users/*`, `/api/v1/users/*` | auth-service / role-service |
| `/api/v1/roles/*` | role-service |
| `/api/inventory/*`, `/api/v1/inventory/*` | inventory-service |
| `/api/v1/areas/*`, `/api/v1/labs/*` | inventory-service |
| `/api/v1/reservations/*` | reservation-service |
| `/api/v1/lab-schedules/*`, `/api/v1/lab-blocks/*` | reservation-service |
| `/api/v1/availability/*` | reservation-service |
| `/api/v1/tutorial-sessions/*` | reservation-service |
| `/api/v1/notifications/*` | reservation-service |
| `/api/v1/penalties/*` | reservation-service |
| `/api/v1/supply-reservations/*` | supply-reservation-service |
| `WS /api/v1/ws/reservations` | reservation-service (websocket) |

Cada servicio publica además su propia documentación OpenAPI en `/docs` (cuando se accede a su puerto directo).

## Autenticación

El flujo de login se basa en **Google OAuth**:

1. El frontend obtiene un `id_token` de Google.
2. Lo envía a `POST /api/auth/google` (proxy a `auth-service`).
3. `auth-service` valida el token contra Google, crea/recupera el usuario en PocketBase y devuelve un JWT propio.
4. Las llamadas siguientes incluyen `Authorization: Bearer <token>`.

Endpoints adicionales útiles:

- `GET /api/auth/me` — datos del usuario autenticado.
- `GET /api/auth/validate` — validación de token.

## Desarrollo local (sin Docker)

Cada servicio puede correrse manualmente:

```bash
cd <service>
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port <puerto>
```

Hay que exportar las mismas variables de entorno que usa Docker Compose. Para usar Mailpit local conviene levantarlo desde Docker:

```bash
docker run -d -p 1025:1025 -p 8025:8025 axllent/mailpit
```

## Pruebas

```bash
cd reservation-service && pytest
cd inventory-service && pytest
```

## Frontend

El cliente vive en un repositorio separado: [`UCB-labconnect-front`](../UCB-labconnect-front). Por defecto apunta al gateway en `http://localhost:8000`.

## Notas operativas

- `SECRET_KEY` y `JWT_SECRET` **deben** rotarse para producción.
- Las credenciales de PocketBase son superusuario; no commitear el `.env` real.
- Mailpit es solo para desarrollo. En producción configurar SMTP real vía `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_USE_SSL`.
