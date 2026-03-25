"""Script to create equipment_logs collection in PocketBase."""
import httpx
import os
import json

POCKETBASE_URL = os.getenv("POCKETBASE_URL", "https://bd-labconnect.zamoranogamarra.online")
POCKETBASE_IDENTITY = os.getenv("POCKETBASE_IDENTITY", "daniel.zamorano@ucb.edu.bo")
POCKETBASE_PASSWORD = os.getenv("POCKETBASE_PASSWORD", "daniel.zamorano")


def authenticate():
    """Authenticate with PocketBase."""
    with httpx.Client() as client:
        response = client.post(
            f"{POCKETBASE_URL}/api/collections/_superusers/auth-with-password",
            json={
                "identity": POCKETBASE_IDENTITY,
                "password": POCKETBASE_PASSWORD,
            },
        )
        response.raise_for_status()
        return response.json()["token"]


def create_equipment_logs_collection(token):
    """Create equipment_logs collection with fields."""
    fields = [
        {
            "id": "equipment_id",
            "name": "equipment_id",
            "type": "text",
            "required": True,
        },
        {
            "id": "user_id",
            "name": "user_id",
            "type": "text",
            "required": True,
        },
        {
            "id": "status_previous",
            "name": "status_previous",
            "type": "text",
            "required": True,
        },
        {
            "id": "status_new",
            "name": "status_new",
            "type": "text",
            "required": True,
        },
        {
            "id": "changed_at",
            "name": "changed_at",
            "type": "date",
            "required": True,
        },
        {
            "id": "comment",
            "name": "comment",
            "type": "text",
            "required": False,
        },
    ]

    collection_data = {
        "name": "equipment_logs",
        "type": "base",
        "schema": fields,
    }

    with httpx.Client() as client:
        response = client.post(
            f"{POCKETBASE_URL}/api/collections",
            json=collection_data,
            headers={"Authorization": f"Bearer {token}"},
        )
        
        if response.status_code == 201:
            print("✅ Collection 'equipment_logs' created successfully!")
            print(json.dumps(response.json(), indent=2))
        elif response.status_code == 400:
            # Collection might already exist
            error = response.json().get("message", "")
            if "already exists" in error:
                print("⚠️  Collection 'equipment_logs' already exists.")
            else:
                print(f"❌ Error: {error}")
                response.raise_for_status()
        else:
            print(f"❌ Error creating collection: {response.status_code}")
            print(response.text)
            response.raise_for_status()


if __name__ == "__main__":
    print("Creating equipment_logs collection in PocketBase...")
    try:
        token = authenticate()
        print("✅ Authenticated successfully")
        create_equipment_logs_collection(token)
    except Exception as e:
        print(f"❌ Error: {e}")
        exit(1)
