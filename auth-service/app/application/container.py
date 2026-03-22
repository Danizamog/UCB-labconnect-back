from app.application.use_cases.login_user import LoginUser
from app.application.use_cases.register_user import RegisterUser
from app.application.use_cases.validate_token import ValidateToken
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository

user_repository = InMemoryUserRepository()

register_user_use_case = RegisterUser(repository=user_repository)
login_user_use_case = LoginUser(repository=user_repository)
validate_token_use_case = ValidateToken()
