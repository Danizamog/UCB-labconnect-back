from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from datetime import datetime

from app.api.v1.router import api_router
import app.models.asset  # noqa: F401

app = FastAPI(title="LabConnect Inventory Service", version="2.0.0")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inventory-service"}


@app.post("/setup/create-logs-collection")
async def setup_equipment_logs_collection() -> dict:
    """Setup endpoint to create equipment_logs collection in PocketBase."""
    try:
        pocketbase_url = os.getenv("POCKETBASE_URL", "https://bd-labconnect.zamoranogamarra.online")
        identity = os.getenv("POCKETBASE_IDENTITY", "daniel.zamorano@ucb.edu.bo")
        password = os.getenv("POCKETBASE_PASSWORD", "daniel.zamorano")

        # Authenticate
        async with httpx.AsyncClient() as client:
            auth_response = await client.post(
                f"{pocketbase_url}/api/collections/_superusers/auth-with-password",
                json={"identity": identity, "password": password},
            )
            auth_response.raise_for_status()
            token = auth_response.json()["token"]

            # Create collection
            fields = [
                {"id": "equipment_id", "name": "equipment_id", "type": "text", "required": True},
                {"id": "user_id", "name": "user_id", "type": "text", "required": True},
                {"id": "status_previous", "name": "status_previous", "type": "text", "required": True},
                {"id": "status_new", "name": "status_new", "type": "text", "required": True},
                {"id": "changed_at", "name": "changed_at", "type": "date", "required": True},
                {"id": "comment", "name": "comment", "type": "text", "required": False},
            ]

            collection_data = {
                "name": "equipment_logs",
                "type": "base",
                "schema": fields,
            }

            response = await client.post(
                f"{pocketbase_url}/api/collections",
                json=collection_data,
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code == 201:
                return {
                    "success": True,
                    "message": "Collection 'equipment_logs' created successfully!",
                    "collection": response.json(),
                }
            elif response.status_code == 400:
                error_msg = response.json().get("message", "")
                if "already exists" in error_msg:
                    return {
                        "success": True,
                        "message": "Collection 'equipment_logs' already exists",
                    }
                else:
                    return {"success": False, "message": error_msg}
            else:
                return {
                    "success": False,
                    "message": f"Error creating collection: {response.status_code}",
                    "details": response.text,
                }

    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/setup/add-location-field-to-assets")
async def setup_assets_location_field() -> dict:
    """Setup endpoint to ensure required fields exist in assets collection."""
    try:
        pocketbase_url = os.getenv("POCKETBASE_URL", "https://bd-labconnect.zamoranogamarra.online")
        identity = os.getenv("POCKETBASE_IDENTITY", "daniel.zamorano@ucb.edu.bo")
        password = os.getenv("POCKETBASE_PASSWORD", "daniel.zamorano")

        async with httpx.AsyncClient() as client:
            auth_response = await client.post(
                f"{pocketbase_url}/api/collections/_superusers/auth-with-password",
                json={"identity": identity, "password": password},
            )
            auth_response.raise_for_status()
            token = auth_response.json()["token"]
            headers = {"Authorization": f"Bearer {token}"}

            collection_response = await client.get(
                f"{pocketbase_url}/api/collections/assets",
                headers=headers,
            )
            collection_response.raise_for_status()
            collection = collection_response.json()

            fields = collection.get("fields", [])
            
            # New fields to add
            new_fields = [
                {"name": "location", "type": "text", "required": True, "presentable": True, "max": 120},
                {"name": "item_type", "type": "select", "required": True, "values": ["equipo", "herramienta", "reactivo"]},
                {"name": "brand", "type": "text", "required": False, "max": 100},
                {"name": "model", "type": "text", "required": False, "max": 100},
                {"name": "quantity", "type": "number", "required": False},
                {"name": "unit", "type": "select", "required": False, "values": ["ml", "L", "g", "kg", "piezas", "unidades"]},
                {"name": "expiry_date", "type": "date", "required": False},
                {"name": "provider", "type": "text", "required": False, "max": 150},
                {"name": "concentration", "type": "text", "required": False, "max": 100},
            ]
            
            # Check which fields exist and add missing ones
            existing_field_names = {f.get("name") for f in fields}
            fields_to_add = [f for f in new_fields if f["name"] not in existing_field_names]
            
            if not fields_to_add:
                return {
                    "success": True,
                    "message": "All required fields already exist in assets collection",
                }
            
            fields.extend(fields_to_add)

            update_response = await client.patch(
                f"{pocketbase_url}/api/collections/assets",
                json={"fields": fields},
                headers=headers,
            )
            update_response.raise_for_status()

            return {
                "success": True,
                "message": f"Added {len(fields_to_add)} fields to assets collection successfully",
                "added_fields": [f["name"] for f in fields_to_add],
            }
    except Exception as e:
        return {"success": False, "message": str(e)}

app.include_router(api_router)