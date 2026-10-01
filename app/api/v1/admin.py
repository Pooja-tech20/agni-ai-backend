from fastapi import APIRouter, Depends

from app.api.dependencies import require_role
from app.models.roles import UserRole
from app.models.user import User


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


@router.get("/dashboard")
def admin_dashboard(
    current_user: User = Depends(
        require_role(
            UserRole.ADMIN,
            UserRole.SUPERADMIN,
        )
    ),
):
    return {
        "message": "Welcome to Admin Dashboard",
        "user_id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role,
    }