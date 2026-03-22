from app.application.use_cases.manage_roles import ManageRolesUseCase
from app.infrastructure.repositories.in_memory_role_repository import InMemoryRoleRepository

role_repository = InMemoryRoleRepository()
manage_roles_use_case = ManageRolesUseCase(repository=role_repository)
