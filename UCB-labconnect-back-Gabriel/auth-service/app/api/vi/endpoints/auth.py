from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.core.dependencies import get_db, get_current_user, require_admin
from app.core.security import create_access_token, get_password_hash, verify_password
from app.core.config import settings
from app.models.user import User
from app.schemas.auth import LoginResponse, UserCreate, UserOut, GoogleTokenIn
from app.services.redis_service import redis_client

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    existing_username = db.query(User).filter(User.username == user_in.username).first()
    if existing_username:
        raise HTTPException(status_code=400, detail="El username ya existe")

    existing_email = db.query(User).filter(User.email == user_in.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="El email ya existe")

    new_user = User(
        username=user_in.username,
        full_name=user_in.full_name,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/login", response_model=LoginResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form_data.username.strip().lower()

    if not email.endswith("@ucb.edu.bo"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permite iniciar sesión con correos @ucb.edu.bo",
        )

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
        )

    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
        )

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "user_id": user.id}
    )

    await redis_client.setex(f"session:{user.id}", 7200, access_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.post("/google-login", response_model=LoginResponse)
async def google_login(payload: GoogleTokenIn, db: Session = Depends(get_db)):
    try:
        idinfo = id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            audience=settings.google_client_id,
        )

        email = idinfo.get("email")
        full_name = idinfo.get("name") or "Usuario Google"
        google_sub = idinfo.get("sub")
        email_verified = idinfo.get("email_verified", False)
        hosted_domain = idinfo.get("hd")

        if not email or not email_verified:
            raise HTTPException(status_code=400, detail="Cuenta de Google no válida")

        # Regla fuerte: solo cuentas Google Workspace del dominio UCB
        if hosted_domain != settings.allowed_google_domain:
            raise HTTPException(
                status_code=403,
                detail=f"Solo se permite iniciar sesión con cuentas @{settings.allowed_google_domain}",
            )

        # Defensa adicional: el email también debe terminar en ese dominio
        if not email.lower().endswith(f"@{settings.allowed_google_domain}"):
            raise HTTPException(
                status_code=403,
                detail=f"Solo se permite iniciar sesión con cuentas @{settings.allowed_google_domain}",
            )

        user = db.query(User).filter(User.email == email).first()

        if not user:
            base_username = email.split("@")[0]
            username = base_username
            counter = 1

            while db.query(User).filter(User.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1

            user = User(
                username=username,
                full_name=full_name,
                email=email,
                hashed_password=get_password_hash(f"google::{google_sub}"),
                role="user",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        access_token = create_access_token(
            data={"sub": user.username, "role": user.role, "user_id": user.id}
        )

        await redis_client.setex(f"session:{user.id}", 7200, access_token)

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": user,
        }

    except ValueError:
        raise HTTPException(status_code=401, detail="Token de Google inválido")

@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/admin-only")
def admin_only(current_user: User = Depends(require_admin)):
    return {"message": f"Hola admin {current_user.full_name}"}