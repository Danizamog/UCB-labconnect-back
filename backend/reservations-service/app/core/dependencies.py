from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8001/api/v1/auth/login")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("user_id")
        username = payload.get("sub")
        role = payload.get("role")

        if user_id is None or username is None:
            raise credentials_exception

        return {
            "user_id": user_id,
            "username": username,
            "role": role,
        }
    except JWTError:
        raise credentials_exception