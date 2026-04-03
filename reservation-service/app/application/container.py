from app.infrastructure.pocketbase_base import PocketBaseClient
from app.infrastructure.repositories.lab_block_repository import LabBlockRepository
from app.infrastructure.repositories.lab_reservation_repository import LabReservationRepository
from app.infrastructure.repositories.lab_schedule_repository import LabScheduleRepository
from app.penalties.store import penalty_store

_pb_client = PocketBaseClient()

lab_reservation_repo = LabReservationRepository(_pb_client)
lab_schedule_repo = LabScheduleRepository(_pb_client)
lab_block_repo = LabBlockRepository(_pb_client)
user_penalty_repo = penalty_store
