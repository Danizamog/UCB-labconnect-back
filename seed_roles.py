#!/usr/bin/env python3
"""
Seed script for initializing main roles in PocketBase.
Loads: Administrador, Docente, Estudiante, Ayudante de Laboratorio
"""

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

POCKETBASE_URL = os.getenv("POCKETBASE_URL")
POCKETBASE_AUTH_IDENTITY = os.getenv("POCKETBASE_AUTH_IDENTITY")
POCKETBASE_AUTH_PASSWORD = os.getenv("POCKETBASE_AUTH_PASSWORD")
POCKETBASE_AUTH_COLLECTION = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
POCKETBASE_ROLE_COLLECTION = os.getenv("POCKETBASE_ROLE_COLLECTION", "role")

if not POCKETBASE_URL or not POCKETBASE_AUTH_IDENTITY or not POCKETBASE_AUTH_PASSWORD:
    print("ERROR: Missing PocketBase credentials in .env")
    sys.exit(1)

ROLES = [
    {
        "nombre": "Administrador",
        "descripcion": "Acceso total al sistema: gestión de roles, usuarios, inventario y configuración.",
        "permisos": [
            "gestionar_roles_permisos",
            "reactivar_cuentas",
            "gestionar_reservas",
            "gestionar_reservas_materiales",
            "gestionar_reglas_reserva",
            "gestionar_inventario",
            "gestionar_stock",
            "gestionar_estado_equipos",
            "gestionar_mantenimiento",
            "gestionar_prestamos",
            "adjuntar_evidencia_inventario",
            "gestionar_accesos_laboratorio",
            "gestionar_penalizaciones",
            "gestionar_tutorias",
            "gestionar_inscripciones_tutorias",
            "gestionar_asistencia_tutorias",
            "gestionar_observaciones_tutorias",
            "gestionar_notificaciones",
            "generar_reportes",
            "consultar_estadisticas",
            "gestionar_reactivos_quimicos",
            "controlar_compatibilidad_quimica",
            "gestionar_hojas_seguridad_msds",
            "gestionar_residuos_quimicos",
            "gestionar_epp_bioseguridad",
            "gestionar_incidentes_laboratorio",
            "autorizar_practicas_riesgo",
            "gestionar_calibracion_instrumentos",
        ],
    },
    {
        "nombre": "Docente",
        "descripcion": "Gestión de tutorías, consulta de reservas, acceso a estadísticas de laboratorio.",
        "permisos": [
            "gestionar_tutorias",
            "gestionar_inscripciones_tutorias",
            "gestionar_asistencia_tutorias",
            "gestionar_observaciones_tutorias",
            "gestionar_reservas",
            "consultar_estadisticas",
            "gestionar_notificaciones",
            "gestionar_accesos_laboratorio",
            "autorizar_practicas_riesgo",
            "generar_reportes",
        ],
    },
    {
        "nombre": "Estudiante",
        "descripcion": "Acceso limitado: crear/ver reservas, consultar stock, registrar asistencia a tutorías.",
        "permisos": [
            "gestionar_reservas",
            "gestionar_inscripciones_tutorias",
            "gestionar_asistencia_tutorias",
        ],
    },
    {
        "nombre": "Ayudante de Laboratorio",
        "descripcion": "Gestión de inventario, stock, equipo, mantenimiento y control de acceso.",
        "permisos": [
            "gestionar_inventario",
            "gestionar_stock",
            "gestionar_estado_equipos",
            "gestionar_mantenimiento",
            "gestionar_prestamos",
            "adjuntar_evidencia_inventario",
            "gestionar_accesos_laboratorio",
            "gestionar_reactivos_quimicos",
            "controlar_compatibilidad_quimica",
            "gestionar_hojas_seguridad_msds",
            "gestionar_residuos_quimicos",
            "gestionar_epp_bioseguridad",
            "gestionar_incidentes_laboratorio",
            "gestionar_calibracion_instrumentos",
            "consultar_estadisticas",
        ],
    },
]


class PocketBaseSeeder:
    def __init__(self):
        self.auth_token = None
        self.base_url = POCKETBASE_URL.rstrip("/")
        self.records_endpoint = f"{self.base_url}/api/collections/{POCKETBASE_ROLE_COLLECTION}/records"

    def authenticate(self):
        """Authenticate against PocketBase and get auth token."""
        print(f"Authenticating as {POCKETBASE_AUTH_IDENTITY}...")
        auth_endpoints = [
            f"{self.base_url}/api/collections/{POCKETBASE_AUTH_COLLECTION}/auth-with-password",
            f"{self.base_url}/api/admins/auth-with-password",
        ]

        for endpoint in auth_endpoints:
            try:
                response = httpx.post(
                    endpoint,
                    json={
                        "identity": POCKETBASE_AUTH_IDENTITY,
                        "password": POCKETBASE_AUTH_PASSWORD,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                self.auth_token = data.get("token")
                if self.auth_token:
                    print(f"✓ Authenticated successfully")
                    return
            except httpx.HTTPStatusError:
                continue
            except Exception as e:
                print(f"Error testing endpoint {endpoint}: {e}")
                continue

        raise RuntimeError("Failed to authenticate against PocketBase")

    def _request(self, method: str, url: str, **kwargs):
        """Make HTTP request with authentication."""
        headers = kwargs.pop("headers", {})
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        response = httpx.request(method, url, headers=headers, timeout=10, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def seed_roles(self):
        """Create or update roles in PocketBase."""
        print(f"\nSeeding {len(ROLES)} roles to PocketBase...\n")

        for role_data in ROLES:
            try:
                # Try to find existing role by name
                filter_query = f'name="{role_data["nombre"]}"'
                response = self._request(
                    "GET",
                    self.records_endpoint,
                    params={"filter": filter_query, "perPage": 1},
                )

                items = response.get("items", []) if isinstance(response, dict) else []
                existing_role = items[0] if items else None

                payload = {
                    "name": role_data["nombre"],
                    "descripcion": role_data["descripcion"],
                    "permisos": role_data["permisos"],
                }

                if existing_role:
                    # Update existing role
                    self._request(
                        "PATCH",
                        f"{self.records_endpoint}/{existing_role['id']}",
                        json=payload,
                    )
                    print(f"✓ Updated role: {role_data['nombre']}")
                else:
                    # Create new role
                    self._request(
                        "POST",
                        self.records_endpoint,
                        json=payload,
                    )
                    print(f"✓ Created role: {role_data['nombre']}")

            except Exception as e:
                print(f"✗ Error processing role '{role_data['nombre']}': {e}")
                raise

        print(f"\n✓ Seeding completed successfully!")


if __name__ == "__main__":
    try:
        seeder = PocketBaseSeeder()
        seeder.authenticate()
        seeder.seed_roles()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
