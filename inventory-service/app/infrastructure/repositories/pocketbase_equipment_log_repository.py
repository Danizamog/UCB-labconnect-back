"""Repository for equipment status change logs in PocketBase."""
import httpx
from datetime import datetime
from typing import Optional


class PocketBaseEquipmentLogRepository:
    """Manages equipment status change logs stored in PocketBase."""

    def __init__(
        self,
        pocketbase_url: str,
        identity: str,
        password: str,
    ):
        self.pocketbase_url = pocketbase_url
        self.identity = identity
        self.password = password
        self.collection_name = "equipment_logs"
        self.auth_token = None

    async def _authenticate(self) -> str:
        """Authenticate with PocketBase and return auth token."""
        if self.auth_token:
            return self.auth_token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.pocketbase_url}/api/collections/_superusers/auth-with-password",
                json={
                    "identity": self.identity,
                    "password": self.password,
                },
            )
            response.raise_for_status()
            data = response.json()
            self.auth_token = data.get("token")
            return self.auth_token

    async def create_log(
        self,
        equipment_id: str,
        user_id: str,
        previous_status: str,
        new_status: str,
        comment: Optional[str] = None,
    ) -> dict:
        """Create a new equipment status change log."""
        token = await self._authenticate()

        log_data = {
            "equipment_id": equipment_id,
            "user_id": user_id,
            "status_previous": previous_status,
            "status_new": new_status,
            "changed_at": datetime.utcnow().isoformat(),
        }
        if comment:
            log_data["comment"] = comment

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.pocketbase_url}/api/collections/{self.collection_name}/records",
                json=log_data,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()

    async def get_equipment_logs(self, equipment_id: str, limit: int = 50) -> list:
        """Get all status change logs for a specific equipment."""
        token = await self._authenticate()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.pocketbase_url}/api/collections/{self.collection_name}/records",
                params={
                    "filter": f'equipment_id = "{equipment_id}"',
                    "sort": "-changed_at",
                    "perPage": limit,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])

    async def get_all_logs(self, limit: int = 100) -> list:
        """Get all equipment status change logs."""
        token = await self._authenticate()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.pocketbase_url}/api/collections/{self.collection_name}/records",
                params={
                    "sort": "-changed_at",
                    "perPage": limit,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])
