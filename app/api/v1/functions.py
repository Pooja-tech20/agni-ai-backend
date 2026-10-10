"""
Functions (tools) an agent's LLM can call during a conversation.

GET    /functions/types     what kinds exist + the config schema of each
GET    /functions           list / search (your organization)
POST   /functions           create          (admin)
GET    /functions/{id}      one function
PATCH  /functions/{id}      partial update  (admin)
DELETE /functions/{id}      delete          (admin; blocked while an agent uses it)
"""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.agent import Agent
from app.models.client import Client
from app.models.function import AgentFunction
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.function import (
    CONFIG_MODELS,
    MASK,
    TYPE_INFO,
    FunctionCreateRequest,
    FunctionListResponse,
    FunctionResponse,
    FunctionType,
    FunctionTypeInfo,
    FunctionUpdateRequest,
    mask_config,
    validate_config,
)

router = APIRouter(prefix="/functions", tags=["Functions"])

admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)

NAME_TAKEN = "A function with this name already exists"


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


def _to_response(fn: AgentFunction) -> FunctionResponse:
    return FunctionResponse(
        id=fn.id,
        client_id=fn.client_id,
        name=fn.name,
        description=fn.description,
        type=fn.type,
        config=mask_config(fn.type, fn.config),  # never send header secrets back
        enabled=fn.enabled,
        created_at=fn.created_at,
        updated_at=fn.updated_at,
    )


def _get_or_404(db: Session, function_id: uuid.UUID, user: User) -> AgentFunction:
    fn = db.get(AgentFunction, function_id)
    # Same 404 whether it doesn't exist or belongs to another organization
    if not fn or (not _is_super(user) and fn.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Function not found")
    return fn


def _name_taken(db: Session, client_id: uuid.UUID, name: str, exclude_id=None) -> bool:
    q = db.query(AgentFunction.id).filter(
        AgentFunction.client_id == client_id, func.lower(AgentFunction.name) == name.lower()
    )
    if exclude_id:
        q = q.filter(AgentFunction.id != exclude_id)
    return q.first() is not None


def _checked_config(type_: str, config: dict[str, Any]) -> dict[str, Any]:
    """Validate a config; on failure return a 422 that does NOT echo the input
    (it may contain secret header values)."""
    try:
        return validate_config(type_, config)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {"loc": ["config", *map(str, e["loc"])], "msg": e["msg"]}
                for e in exc.errors(include_url=False, include_context=False)
            ],
        )


def _restore_masked_headers(new_config: dict[str, Any], old_config: dict[str, Any]) -> None:
    """The browser sends back the masked header values it received. Where a value is
    still masked, keep the stored secret instead of overwriting it with dots."""
    headers = new_config.get("headers")
    if not isinstance(headers, dict):
        return
    old_headers = old_config.get("headers") or {}
    for name, value in list(headers.items()):
        if isinstance(value, str) and value.startswith(MASK):
            if name in old_headers:
                headers[name] = old_headers[name]
            else:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Header '{name}' has no stored value. Send the real value.",
                )


def _agents_using(db: Session, client_id: uuid.UUID, function_id: uuid.UUID) -> list[str]:
    """Names of agents whose `functions` list references this function by id."""
    wanted = str(function_id)
    used = []
    for name, functions in db.query(Agent.name, Agent.functions).filter(Agent.client_id == client_id):
        if any(isinstance(f, dict) and str(f.get("id") or f.get("function_id")) == wanted for f in functions or []):
            used.append(name)
    return used


# NOTE: declared before "/{function_id}" so "types" is not parsed as an id.
@router.get("/types", response_model=list[FunctionTypeInfo])
def list_function_types(current_user: User = Depends(get_current_user)):
    """Kinds of functions, each with a JSON Schema so the UI can render its form."""
    return [
        FunctionTypeInfo(
            type=key,
            label=TYPE_INFO[key][0],
            description=TYPE_INFO[key][1],
            config_schema=model.model_json_schema(),
        )
        for key, model in CONFIG_MODELS.items()
    ]


@router.get("", response_model=FunctionListResponse)
def list_functions(
    search: str | None = Query(None, description="Match part of the name or description"),
    type_: FunctionType | None = Query(None, alias="type"),
    enabled: bool | None = None,
    client_id: uuid.UUID | None = Query(None, description="Superadmin only"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(AgentFunction)
    if _is_super(current_user):
        if client_id:
            q = q.filter(AgentFunction.client_id == client_id)
    else:
        q = q.filter(AgentFunction.client_id == current_user.client_id)

    if type_:
        q = q.filter(AgentFunction.type == type_)
    if enabled is not None:
        q = q.filter(AgentFunction.enabled == enabled)
    if search and search.strip():
        like = f"%{search.strip()}%"
        q = q.filter(AgentFunction.name.ilike(like) | AgentFunction.description.ilike(like))

    total = q.count()
    rows = (
        q.order_by(AgentFunction.created_at.desc(), AgentFunction.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return FunctionListResponse(total=total, items=[_to_response(f) for f in rows])


@router.post("", response_model=FunctionResponse, status_code=status.HTTP_201_CREATED)
def create_function(
    request: FunctionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    if _is_super(current_user):
        client_id = request.client_id
        if client_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "client_id is required")
        if not db.get(Client, client_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    else:
        if request.client_id and request.client_id != current_user.client_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You can only create functions in your own organization"
            )
        client_id = current_user.client_id
        if client_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account has no organization")

    config = _checked_config(request.type, request.config)

    if _name_taken(db, client_id, request.name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NAME_TAKEN)

    fn = AgentFunction(
        client_id=client_id,
        name=request.name,
        description=request.description,
        type=request.type,
        config=config,
        enabled=request.enabled,
    )
    db.add(fn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # lost a race with a request using the same name
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NAME_TAKEN)
    db.refresh(fn)
    return _to_response(fn)


@router.get("/{function_id}", response_model=FunctionResponse)
def get_function(
    function_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _to_response(_get_or_404(db, function_id, current_user))


@router.patch("/{function_id}", response_model=FunctionResponse)
def update_function(
    function_id: uuid.UUID,
    request: FunctionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    fn = _get_or_404(db, function_id, current_user)
    changes = request.model_dump(exclude_unset=True)

    for field in ("name", "description", "config", "enabled"):
        if field in changes and changes[field] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} cannot be null")

    if "name" in changes and changes["name"].lower() != fn.name.lower():
        if _name_taken(db, fn.client_id, changes["name"], exclude_id=fn.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, NAME_TAKEN)

    if "config" in changes:
        new_config = dict(changes["config"])
        if fn.type == "webhook":
            _restore_masked_headers(new_config, fn.config)
        changes["config"] = _checked_config(fn.type, new_config)

    for field, value in changes.items():
        setattr(fn, field, value)  # config is replaced, never mutated in place

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NAME_TAKEN)
    db.refresh(fn)
    return _to_response(fn)


@router.delete("/{function_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_function(
    function_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    fn = _get_or_404(db, function_id, current_user)
    agents = _agents_using(db, fn.client_id, fn.id)
    if agents:
        shown = ", ".join(agents[:5]) + ("..." if len(agents) > 5 else "")
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This function is used by {len(agents)} agent(s): {shown}. Remove it from them first.",
        )
    db.delete(fn)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)