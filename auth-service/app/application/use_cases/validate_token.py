from app.infrastructure.security.token_provider import decode_token


class ValidateToken:
    def execute(self, token: str) -> dict:
        return decode_token(token)
