# Plantilla de Microservicios Python (Lab Management)

Plantilla mínima para una app de gestión de laboratorios con:

- API Gateway (`FastAPI`)
- Auth Service (`FastAPI` + `JWT`)
- Docker Compose para orquestar los servicios

## Estructura

```
.
├── docker-compose.yml
├── .env.example
└── services
    ├── api-gateway
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── app/main.py
    └── auth-service
        ├── Dockerfile
        ├── requirements.txt
        └── app/main.py
```

## Cómo se conectan

1. El cliente llama al `API Gateway` en `http://localhost:8000`.
2. El gateway redirige rutas `/api/auth/*` hacia `auth-service` interno: `http://auth-service:8001/*`.
3. `auth-service` procesa registro/login/validación y responde al gateway.
4. El gateway devuelve la respuesta al cliente.

Flujo lógico:

`Client -> API Gateway (/api/auth/*) -> Auth Service -> API Gateway -> Client`

## Levantar con Docker

```bash
docker compose up --build
```

Servicios:

- Gateway: `http://localhost:8000`
- Auth: `http://localhost:8001`

## Endpoints del Auth (vía Gateway)

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/validate`

### 1) Registrar usuario

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

### 2) Login

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

Respuesta esperada (resumen):

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### 3) Validar token

```bash
curl http://localhost:8000/api/auth/validate \
  -H "Authorization: Bearer TU_TOKEN"
```

## Notas para producción

- La plantilla guarda usuarios en memoria (`users_db`) para arrancar rápido.
- Reemplaza por base de datos (PostgreSQL/MySQL) y migraciones.
- Cambia `SECRET_KEY` por una clave segura.
