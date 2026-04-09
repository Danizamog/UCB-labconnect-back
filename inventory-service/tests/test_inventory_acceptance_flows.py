from __future__ import annotations

import unittest
from threading import Lock

from app.infrastructure.repositories.asset_maintenance_repository import AssetMaintenanceRepository
from app.infrastructure.repositories.loan_record_repository import LoanRecordRepository
from app.schemas.asset import AssetResponse
from app.schemas.asset_maintenance import AssetMaintenanceTicketClose, AssetMaintenanceTicketCreate
from app.schemas.loan_record import LoanRecordCreate, LoanRecordReturn


class _FakeAdminClient:
    def __init__(self) -> None:
        self.enabled = True
        self.records: dict[str, dict[str, dict]] = {}
        self.counter = 0

    def ensure_collection(self, collection: str, _fields) -> None:
        self.records.setdefault(collection, {})

    def get_collection(self, _collection: str) -> dict:
        return {"id": "asset-collection"}

    def create_record(self, collection: str, payload: dict) -> dict:
        self.counter += 1
        record_id = f"rec-{self.counter}"
        record = {"id": record_id, **payload}
        self.records.setdefault(collection, {})[record_id] = record
        return record

    def update_record(self, collection: str, record_id: str, payload: dict) -> dict:
        record = self.records.setdefault(collection, {}).get(record_id, {"id": record_id})
        record.update(payload)
        self.records[collection][record_id] = record
        return record

    def get_record(self, collection: str, record_id: str) -> dict | None:
        return self.records.get(collection, {}).get(record_id)

    def list_records(self, collection: str, sort: str | None = None) -> list[dict]:
        items = list(self.records.get(collection, {}).values())
        if sort and sort.startswith("-"):
            key = sort[1:]
            items.sort(key=lambda item: str(item.get(key) or ""), reverse=True)
        return items


class _FakeBaseClient:
    def __init__(self, asset_source_id: str = "source-asset-1") -> None:
        self.asset_source_id = asset_source_id

    def request(self, method: str, path: str):
        if method == "GET" and path.endswith("/asset-1"):
            return {"id": "asset-1", "source_id": self.asset_source_id}
        raise AssertionError(f"Unexpected request {method} {path}")


class _FakeAssetRepo:
    def __init__(self, status: str = "available") -> None:
        self.asset = AssetResponse(
            id="asset-1",
            serial_number="EQ-001",
            name="Osciloscopio",
            category="Medicion",
            location="Gabinete A-01",
            description="Equipo para practicas de medicion.",
            status=status,
            laboratory_id="lab-1",
            laboratory_name="Lab Electronica",
            status_updated_at="",
            status_updated_by="",
            created="",
            updated="",
        )
        self.updates: list[dict] = []

    def get_by_id(self, asset_id: str):
        return self.asset if asset_id == self.asset.id else None

    def update(self, asset_id: str, body):
        if asset_id != self.asset.id:
            return None
        payload = {key: value for key, value in body.model_dump().items() if value is not None}
        self.updates.append(payload)
        self.asset = self.asset.model_copy(update=payload)
        return self.asset


class _FakeUserDirectoryRepo:
    def resolve(self, **kwargs):
        return {
            "id": kwargs.get("identifier") or "student-1",
            "name": "Student One",
            "email": "student1@ucb.edu.bo",
            "role": "student",
            "is_active": True,
        }


def _build_maintenance_repo(*, asset_repo: _FakeAssetRepo, admin_client: _FakeAdminClient | None = None) -> AssetMaintenanceRepository:
    repo = object.__new__(AssetMaintenanceRepository)
    repo._client = _FakeBaseClient()
    repo._asset_repo = asset_repo
    repo._collection = "asset_maintenance_ticket"
    repo._loan_collection = "loan_record"
    repo._admin_client = admin_client or _FakeAdminClient()
    repo._collection_ready = True
    repo._collection_lock = Lock()
    return repo


def _build_loan_repo(
    *,
    asset_repo: _FakeAssetRepo,
    maintenance_repo: AssetMaintenanceRepository,
    admin_client: _FakeAdminClient | None = None,
) -> LoanRecordRepository:
    repo = object.__new__(LoanRecordRepository)
    repo._client = _FakeBaseClient()
    repo._asset_repo = asset_repo
    repo._asset_maintenance_repo = maintenance_repo
    repo._user_directory_repo = _FakeUserDirectoryRepo()
    repo._collection = "loan_record"
    repo._admin_client = admin_client or _FakeAdminClient()
    repo._collection_ready = True
    repo._collection_lock = Lock()
    return repo


class InventoryAcceptanceTests(unittest.TestCase):
    def test_damage_ticket_moves_asset_to_maintenance_and_flags_latest_borrower(self) -> None:
        asset_repo = _FakeAssetRepo(status="available")
        admin_client = _FakeAdminClient()
        admin_client.records["loan_record"] = {
            "loan-1": {
                "id": "loan-1",
                "asset_id": "source-asset-1",
                "borrower_name": "Student One",
                "borrower_email": "student1@ucb.edu.bo",
                "loaned_at": "2026-04-09T10:00:00Z",
            }
        }
        repo = _build_maintenance_repo(asset_repo=asset_repo, admin_client=admin_client)

        ticket = repo.create(
            "asset-1",
            AssetMaintenanceTicketCreate(
                ticket_type="damage",
                title="Pantalla rota",
                description="La pantalla presenta una grieta visible despues del prestamo.",
                severity="high",
                evidence_report_id="DANO-001",
            ),
            current_user={"username": "encargado", "user_id": "staff-1", "email": "staff@ucb.edu.bo"},
        )

        self.assertEqual(ticket.status, "open")
        self.assertTrue(ticket.is_responsibility_flagged)
        self.assertEqual(ticket.related_loan_id, "loan-1")
        self.assertEqual(ticket.responsible_borrower_email, "student1@ucb.edu.bo")
        self.assertEqual(asset_repo.asset.status, "maintenance")

    def test_closing_ticket_returns_asset_to_available(self) -> None:
        asset_repo = _FakeAssetRepo(status="maintenance")
        admin_client = _FakeAdminClient()
        admin_client.records["asset_maintenance_ticket"] = {
            "ticket-1": {
                "id": "ticket-1",
                "asset_id": "asset-1",
                "asset_name": "Osciloscopio",
                "ticket_type": "maintenance",
                "title": "Revision general",
                "description": "Se requiere calibracion preventiva.",
                "severity": "medium",
                "evidence_report_id": "MTTO-001",
                "status": "open",
                "reported_at": "2026-04-09T10:00:00Z",
                "reported_by": "encargado",
            }
        }
        repo = _build_maintenance_repo(asset_repo=asset_repo, admin_client=admin_client)

        closed = repo.close(
            "ticket-1",
            AssetMaintenanceTicketClose(resolution_notes="Equipo calibrado y verificado."),
            current_user={"username": "encargado", "user_id": "staff-1", "email": "staff@ucb.edu.bo"},
        )

        self.assertEqual(closed.status, "closed")
        self.assertEqual(asset_repo.asset.status, "available")

    def test_loan_marks_asset_as_loaned_and_stores_timestamp(self) -> None:
        asset_repo = _FakeAssetRepo(status="available")
        maintenance_repo = _build_maintenance_repo(asset_repo=asset_repo)
        admin_client = _FakeAdminClient()
        repo = _build_loan_repo(asset_repo=asset_repo, maintenance_repo=maintenance_repo, admin_client=admin_client)

        loan = repo.create(
            LoanRecordCreate(
                asset_id="asset-1",
                borrower_id="student-1",
                borrower_name="Student One",
                borrower_email="student1@ucb.edu.bo",
                purpose="Practica de laboratorio",
            ),
            current_user={"username": "encargado", "access_token": "token"},
        )

        self.assertEqual(loan.status, "active")
        self.assertTrue(loan.loaned_at.endswith("Z"))
        self.assertEqual(asset_repo.asset.status, "loaned")

    def test_loan_is_rejected_for_assets_in_maintenance(self) -> None:
        asset_repo = _FakeAssetRepo(status="maintenance")
        maintenance_repo = _build_maintenance_repo(asset_repo=asset_repo)
        repo = _build_loan_repo(asset_repo=asset_repo, maintenance_repo=maintenance_repo)

        with self.assertRaisesRegex(ValueError, "esta en mantenimiento"):
            repo.create(
                LoanRecordCreate(
                    asset_id="asset-1",
                    borrower_id="student-1",
                    borrower_name="Student One",
                    borrower_email="student1@ucb.edu.bo",
                ),
                current_user={"username": "encargado", "access_token": "token"},
            )

    def test_damaged_return_requires_details_and_moves_asset_to_maintenance(self) -> None:
        asset_repo = _FakeAssetRepo(status="loaned")
        maintenance_admin = _FakeAdminClient()
        maintenance_admin.records["loan_record"] = {
            "loan-1": {
                "id": "loan-1",
                "asset_id": "source-asset-1",
                "borrower_name": "Student One",
                "borrower_email": "student1@ucb.edu.bo",
                "loaned_at": "2026-04-09T10:00:00Z",
            }
        }
        maintenance_repo = _build_maintenance_repo(asset_repo=asset_repo, admin_client=maintenance_admin)
        loan_admin = _FakeAdminClient()
        loan_admin.records["loan_record"] = {
            "loan-1": {
                "id": "loan-1",
                "asset_id": "asset-1",
                "asset_name": "Osciloscopio",
                "asset_serial_number": "EQ-001",
                "borrower_id": "student-1",
                "borrower_name": "Student One",
                "borrower_email": "student1@ucb.edu.bo",
                "status": "active",
                "loaned_by": "encargado",
                "loaned_at": "2026-04-09T10:00:00Z",
            }
        }
        repo = _build_loan_repo(asset_repo=asset_repo, maintenance_repo=maintenance_repo, admin_client=loan_admin)

        with self.assertRaisesRegex(ValueError, "Debes describir el problema"):
            repo.return_loan(
                "loan-1",
                LoanRecordReturn(return_condition="damaged", incident_notes=""),
                current_user={"username": "encargado", "user_id": "staff-1", "email": "staff@ucb.edu.bo"},
            )

        returned = repo.return_loan(
            "loan-1",
            LoanRecordReturn(return_condition="damaged", incident_notes="Golpe en el lateral derecho."),
            current_user={"username": "encargado", "user_id": "staff-1", "email": "staff@ucb.edu.bo"},
        )

        self.assertEqual(returned.status, "returned")
        self.assertEqual(returned.return_condition, "damaged")
        self.assertEqual(asset_repo.asset.status, "maintenance")
        tickets = maintenance_admin.list_records("asset_maintenance_ticket")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["related_loan_id"], "loan-1")


if __name__ == "__main__":
    unittest.main()