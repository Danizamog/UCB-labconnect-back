from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, require_admin
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.auth import (
    GoogleTokenIn,
    LoginResponse,
    UserAdminUpdate,
    UserCreate,
    UserOut,
    UserProfileUpdate,
)
from app.services.redis_service import redis_client

VALID_ROLES = {"admin", "lab_manager", "student"}

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    if not user_in.email.endswith("@ucb.edu.bo"):
        raise HTTPException(status_code=400, detail="Solo se permiten correos @ucb.edu.bo")
    if user_in.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Rol invalido")

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
        phone=None,
        academic_page=None,
        faculty=None,
        career=None,
        student_code=None,
        campus=None,
        bio=None,
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
            detail="Solo se permite iniciar sesion con correos @ucb.edu.bo",
        )

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contrasena incorrectos",
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
            raise HTTPException(status_code=400, detail="Cuenta de Google no valida")

        allowed_email = email.lower().endswith(f"@{settings.allowed_google_domain}")
        allowed_domain = hosted_domain == settings.allowed_google_domain
        if not allowed_email and not allowed_domain:
            raise HTTPException(
                status_code=403,
                detail=f"Solo se permite iniciar sesion con cuentas @{settings.allowed_google_domain}",
            )

        user = db.query(User).filter(User.email == email.lower()).first()

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
                email=email.lower(),
                hashed_password=get_password_hash(f"google::{google_sub}"),
                role="student",
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
        raise HTTPException(status_code=401, detail="Token de Google invalido")


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserOut)
def update_me(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.phone = payload.phone.strip() if payload.phone else None
    current_user.academic_page = payload.academic_page.strip() if payload.academic_page else None
    current_user.faculty = payload.faculty.strip() if payload.faculty else None
    current_user.career = payload.career.strip() if payload.career else None
    current_user.student_code = payload.student_code.strip() if payload.student_code else None
    current_user.campus = payload.campus.strip() if payload.campus else None
    current_user.bio = payload.bio.strip() if payload.bio else None

    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return db.query(User).order_by(User.full_name.asc()).all()


@router.post("/users", response_model=UserOut)
def create_user_by_admin(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return register(payload, db)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserAdminUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    normalized_email = payload.email.strip().lower()
    if not normalized_email.endswith("@ucb.edu.bo"):
        raise HTTPException(status_code=400, detail="Solo se permiten correos @ucb.edu.bo")
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Rol invalido")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    existing_email = db.query(User).filter(User.email == normalized_email, User.id != user_id).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="El email ya existe")

    user.full_name = payload.full_name.strip()
    user.email = normalized_email
    user.role = payload.role
    user.is_active = payload.is_active
    user.phone = payload.phone.strip() if payload.phone else None
    user.academic_page = payload.academic_page.strip() if payload.academic_page else None
    user.faculty = payload.faculty.strip() if payload.faculty else None
    user.career = payload.career.strip() if payload.career else None
    user.student_code = payload.student_code.strip() if payload.student_code else None
    user.campus = payload.campus.strip() if payload.campus else None
    user.bio = payload.bio.strip() if payload.bio else None

    if payload.password:
        user.hashed_password = get_password_hash(payload.password)

    db.commit()
    db.refresh(user)
    return user


@router.get("/admin-only")
def admin_only(current_user: User = Depends(require_admin)):
    return {"message": f"Hola admin {current_user.full_name}"}
