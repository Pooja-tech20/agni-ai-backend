# import uuid

# from fastapi import Depends, HTTPException, status
# from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
# from sqlalchemy.orm import Session

# from app.core.security import decode_access_token
# from app.db.session import get_db
# from app.models.roles import UserRole
# from app.models.user import User


# security = HTTPBearer()


# def get_current_user(
#     credentials: HTTPAuthorizationCredentials = Depends(security),
#     db: Session = Depends(get_db),
# ) -> User:
#     """
#     Get the currently authenticated user from the JWT token.
#     """

#     token = credentials.credentials

#     # Decode JWT token
#     try:
#         payload = decode_access_token(token)
#     except ValueError:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid or expired access token",
#             headers={"WWW-Authenticate": "Bearer"},
#         )

#     # Get user ID from token
#     user_id = payload.get("sub")

#     if not user_id:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid access token",
#             headers={"WWW-Authenticate": "Bearer"},
#         )

#     try:
#         user_uuid = uuid.UUID(str(user_id))
#     except ValueError:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid access token",
#             headers={"WWW-Authenticate": "Bearer"},
#         )

#     # Find user in database
#     user = (
#         db.query(User)
#         .filter(User.id == user_uuid)
#         .first()
#     )

#     # Check active status
#     if not user.is_active:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="User account is inactive",
#         )

#     return user


# def require_role(*allowed_roles: UserRole):
#     def role_checker(
#         current_user: User = Depends(get_current_user),
#     ):
#         if current_user.role not in [role.value for role in allowed_roles]:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="You do not have permission to access this resource",
#             )

#         return current_user

#     return role_checker

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.roles import UserRole
from app.models.user import User


security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Get the currently authenticated user from the JWT token.
    """

    token = credentials.credentials

    # Decode JWT token
    try:
        payload = decode_access_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user ID from token
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Find user in database
    user = (
        db.query(User)
        .filter(User.id == user_uuid)
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check active status
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return user


def require_role(*allowed_roles: UserRole):
    def role_checker(
        current_user: User = Depends(get_current_user),
    ):
        if current_user.role not in [role.value for role in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )

        return current_user

    return role_checker