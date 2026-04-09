import logging

from app.application.use_cases.manage_roles import ManageRolesUseCase
from app.core.config import settings
from app.infrastructure.repositories.in_memory_role_repository import InMemoryRoleRepository
from app.infrastructure.repositories.pocketbase_role_repository import PocketBaseRoleRepository
from app.infrastructure.repositories.postgres_role_repository import PostgresRoleRepository

def _build_postgres_repository() -> PostgresRoleRepository | InMemoryRoleRepository:
	if settings.postgres_url:
		return PostgresRoleRepository(
			postgres_url=settings.postgres_url,
			namespace=settings.local_data_namespace,
		)
	return InMemoryRoleRepository()


if settings.data_mode in {"postgres", "local"}:
	role_repository = _build_postgres_repository()
elif settings.pocketbase_url:
	role_repository = PocketBaseRoleRepository(
		base_url=settings.pocketbase_url,
		collection=settings.pocketbase_role_collection,
		users_collection=settings.pocketbase_users_collection,
		auth_token=settings.pocketbase_auth_token,
		auth_identity=settings.pocketbase_auth_identity,
		auth_password=settings.pocketbase_auth_password,
		auth_collection=settings.pocketbase_auth_collection,
		timeout_seconds=settings.pocketbase_timeout_seconds,
	)
else:
	role_repository = _build_postgres_repository()

shadow_role_repository = (
	_build_postgres_repository()
	if settings.postgres_url and not isinstance(role_repository, PostgresRoleRepository)
	else None
)

logger = logging.getLogger(__name__)

manage_roles_use_case = ManageRolesUseCase(repository=role_repository)
try:
	manage_roles_use_case.ensure_default_roles()
except Exception as exc:  # pragma: no cover - startup resilience for unavailable external DB
	logger.warning("No se pudieron sincronizar los roles iniciales: %s", exc)
	if isinstance(role_repository, PocketBaseRoleRepository):
		role_repository = _build_postgres_repository()
		manage_roles_use_case = ManageRolesUseCase(repository=role_repository)
		manage_roles_use_case.ensure_default_roles()


def sync_shadow_roles_from_primary() -> None:
	if not isinstance(role_repository, PocketBaseRoleRepository) or shadow_role_repository is None:
		return

	try:
		role_ids_by_name = shadow_role_repository.mirror_roles_from_primary(role_repository.list_all())
		mirrored_users = shadow_role_repository.mirror_users_from_primary(role_repository.list_users_with_roles())
		logger.info(
			"Sincronizados %s roles y %s usuarios desde PocketBase al respaldo PostgreSQL",
			len(role_ids_by_name),
			mirrored_users,
		)
	except Exception as exc:  # pragma: no cover - startup resilience for unavailable external DB
		logger.warning("No se pudo sincronizar el respaldo local de roles y usuarios: %s", exc)
