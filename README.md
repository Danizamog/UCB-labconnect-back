# LabConnect_UCB_Backend

## Environment setup

Copy each example file before running the services:

```powershell
Copy-Item .env.example .env
Copy-Item backend/auth-service/.env.example backend/auth-service/.env
Copy-Item backend/inventory-service/.env.example backend/inventory-service/.env
Copy-Item backend/reservations-service/.env.example backend/reservations-service/.env
```

Notes:
- The values included in the examples are safe local-development defaults.
- `GOOGLE_CLIENT_ID` and `ALLOWED_GOOGLE_DOMAIN` are intentionally kept with their real public values.
- Replace every `SECRET_KEY` with a strong private value outside local development.
- `docker-compose.yml` currently uses `auth-service`, `inventory-service`, and `reservations-service`.
