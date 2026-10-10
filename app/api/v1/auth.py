# import uuid

# from app.models.client import Client
# from sqlalchemy.exc import IntegrityError
# from fastapi import APIRouter, Depends, HTTPException, status
# from sqlalchemy.orm import Session

# from app.api.dependencies import get_current_user
# from app.core.config import settings
# from app.core.security import (
#     create_access_token,
#     create_refresh_token,
#     decode_refresh_token,
#     hash_password,
#     verify_password,
# )
# from app.db.session import get_db
# from app.models.user import User
# from app.schemas.auth import (
#     LoginRequest,
#     RefreshRequest,
#     RegisterRequest,
#     TokenResponse,
#     UserResponse,
# )


# router = APIRouter(
#     prefix="/auth",
#     tags=["Authentication"],
# )

# @router.post(
#     "/register",
#     response_model=UserResponse,
#     status_code=status.HTTP_201_CREATED,
# )
# def register(
#     request: RegisterRequest,
#     db: Session = Depends(get_db),
# ):
#     # Check if email already exists
#     existing_user = (
#         db.query(User)
#         .filter(User.email == request.email)
#         .first()
#     )

#     if existing_user:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Email already registered",
#         )

#     # Create a Client for the organization
#     client = Client(
#         name=request.organization_name,
#         email=request.email,
#         phone=f"{request.phone_country_code}{request.phone_number}",
#     )

#     db.add(client)
#     db.flush()

#     # Create new user and link it to the Client
#     user = User(
#         client_id=client.id,  # IMPORTANT: link user to client
#         email=request.email,
#         hashed_password=hash_password(request.password),
#         first_name=request.first_name,
#         last_name=request.last_name,
#         organization_name=request.organization_name,
#         phone_country_code=request.phone_country_code,
#         phone_number=request.phone_number,
#         referral_source=(
#             request.referral_source.value
#             if request.referral_source
#             else None
#         ),
#     )

#     db.add(user)

#     try:
#         db.commit()
#     except IntegrityError:
#         db.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Email already registered",
#         )

#     db.refresh(user)

#     return user



# def _token_response(user: User) -> TokenResponse:
#     return TokenResponse(
#         access_token=create_access_token(user_id=str(user.id), role=user.role),
#         refresh_token=create_refresh_token(user_id=str(user.id), role=user.role),
#         expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
#         user=user,
#     )


# @router.post(
#     "/login",
#     response_model=TokenResponse,
# )
# def login(
#     request: LoginRequest,
#     db: Session = Depends(get_db),
# ):
#     # Find user by email
#     user = (
#         db.query(User)
#         .filter(User.email == request.email)
#         .first()
#     )

#     # Check credentials
#     if not user or not verify_password(
#         request.password,
#         user.hashed_password,
#     ):
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid email or password",
#         )

#     # Check active status
#     if not user.is_active:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="User account is inactive",
#         )

#     return _token_response(user)


# @router.post(
#     "/refresh",
#     response_model=TokenResponse,
# )
# def refresh(
#     request: RefreshRequest,
#     db: Session = Depends(get_db),
# ):
#     """Exchange a refresh token for a new access token (and a new refresh token),
#     so the user is not logged out when the short-lived access token expires."""
#     invalid = HTTPException(
#         status_code=status.HTTP_401_UNAUTHORIZED,
#         detail="Invalid or expired refresh token",
#         headers={"WWW-Authenticate": "Bearer"},
#     )
#     try:
#         user_id = uuid.UUID(str(decode_refresh_token(request.refresh_token).get("sub")))
#     except ValueError:
#         raise invalid

#     user = db.get(User, user_id)
#     if user is None or not user.is_active:
#         raise invalid

#     return _token_response(user)


# @router.get(
#     "/me",
#     response_model=UserResponse,
# )
# def get_me(
#     current_user: User = Depends(get_current_user),
# ):
#     return current_user

import uuid

from app.models.client import Client
from sqlalchemy.exc import IntegrityError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    # Check if email already exists
    existing_user = (
        db.query(User)
        .filter(User.email == request.email)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create a Client for the organization
    client = Client(
        name=request.organization_name,
        email=request.email,
        phone=f"{request.phone_country_code}{request.phone_number}",
    )

    db.add(client)
    db.flush()

    # Create new user and link it to the Client
    user = User(
        client_id=client.id,  # IMPORTANT: link user to client
        role=UserRole.ADMIN.value,  # first user of a new org owns it
        email=request.email,
        hashed_password=hash_password(request.password),
        first_name=request.first_name,
        last_name=request.last_name,
        organization_name=request.organization_name,
        phone_country_code=request.phone_country_code,
        phone_number=request.phone_number,
        referral_source=(
            request.referral_source.value
            if request.referral_source
            else None
        ),
    )

    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    db.refresh(user)

    return user



def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id=str(user.id), role=user.role),
        refresh_token=create_refresh_token(user_id=str(user.id), role=user.role),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
)
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    # Find user by email
    user = (
        db.query(User)
        .filter(User.email == request.email)
        .first()
    )

    # Check credentials
    if not user or not verify_password(
        request.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Check active status
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return _token_response(user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
)
def refresh(
    request: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Exchange a refresh token for a new access token (and a new refresh token),
    so the user is not logged out when the short-lived access token expires."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = uuid.UUID(str(decode_refresh_token(request.refresh_token).get("sub")))
    except ValueError:
        raise invalid

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid

    return _token_response(user)


@router.get(
    "/me",
    response_model=UserResponse,
)
def get_me(
    current_user: User = Depends(get_current_user),
):
    return current_user