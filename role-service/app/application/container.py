from app.application.use_cases.manage_roles import ManageRolesUseCase
from app.core.config import settings
from app.infrastructure.repositories.in_memory_role_repository import InMemoryRoleRepository
from app.infrastructure.repositories.pocketbase_role_repository import PocketBaseRoleRepository

if settings.pocketbase_url:
	role_repository = PocketBaseRoleRepository(
		base_url=settings.pocketbase_url,
		collection=settings.pocketbase_collection,
		auth_token=settings.pocketbase_auth_token,
		timeout_seconds=settings.pocketbase_timeout_seconds,
	)
else:
	role_repository = InMemoryRoleRepository()

manage_roles_use_case = ManageRolesUseCase(repository=role_repository)
