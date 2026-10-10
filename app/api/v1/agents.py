# import uuid

# from fastapi import (
#     APIRouter,
#     Depends,
#     HTTPException,
#     Query,
#     status,
# )
# from pydantic import ValidationError
# from sqlalchemy.exc import IntegrityError
# from sqlalchemy.orm import Session

# from app.db.session import get_db

# from app.models.agent import Agent
# from app.models.call import Call
# from app.models.client import Client
# from app.models.function import AgentFunction
# from app.models.knowledge_base import KnowledgeBase
# from app.models.user import User, UserRole

# from app.schemas.agent import (
#     AgentCreateRequest,
#     AgentListResponse,
#     AgentResponse,
#     AgentStatus,
#     AgentSummary,
#     AgentUpdateRequest,
#     DEFAULT_AGENT_NAME,
# )

# from app.schemas.function import (
#     TYPE_INFO,
#     validate_config,
# )

# from app.api.dependencies import require_role


# router = APIRouter(
#     prefix="/agents",
#     tags=["Agents"],
# )


# # ============================================================
# # ROLE
# # ============================================================

# admin_or_super = require_role(
#     UserRole.ADMIN,
#     UserRole.SUPERADMIN,
# )


# # ============================================================
# # HELPERS
# # ============================================================

# def _is_super(
#     current_user: User,
# ) -> bool:

#     return (
#         current_user.role
#         == UserRole.SUPERADMIN
#     )


# def _call_count(
#     db: Session,
#     agent_id: uuid.UUID,
# ) -> int:

#     return (
#         db.query(Call)
#         .filter(
#             Call.agent_id == agent_id
#         )
#         .count()
#     )


# def _to_response(
#     agent: Agent,
#     total_calls: int = 0,
# ) -> AgentResponse:

#     return AgentResponse(
#         id=agent.id,
#         name=agent.name,
#         status=agent.status,
#         client_id=agent.client_id,

#         system_prompt=agent.system_prompt,
#         welcome_message=agent.welcome_message,
#         llm_model=agent.llm_model,
#         voice=agent.voice,
#         memory_enabled=agent.memory_enabled,
#         emotion=agent.emotion,
#         accent=agent.accent,
#         timezone=agent.timezone,

#         functions=agent.functions or [],
#         calendars=agent.calendars or [],
#         knowledge_base=agent.knowledge_base or [],
#         crm_sync=agent.crm_sync or {},
#         speech_settings=agent.speech_settings or {},
#         call_settings=agent.call_settings or {},
#         post_call_extraction=(
#             agent.post_call_extraction or {}
#         ),
#         webhook_settings=(
#             agent.webhook_settings or {}
#         ),
#         prompt_variables=(
#             agent.prompt_variables or {}
#         ),
#         agent_metadata=(
#             agent.agent_metadata or {}
#         ),

#         total_calls=total_calls,

#         created_at=agent.created_at,
#         updated_at=agent.updated_at,
#     )


# def _get_agent_or_404(
#     db: Session,
#     agent_id: uuid.UUID,
#     current_user: User,
# ) -> Agent:

#     agent = (
#         db.query(Agent)
#         .filter(
#             Agent.id == agent_id
#         )
#         .first()
#     )

#     if not agent:

#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Agent not found",
#         )

#     if not _is_super(current_user):

#         if (
#             agent.client_id
#             != current_user.client_id
#         ):

#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail=(
#                     "You can access agents only "
#                     "in your own organization"
#                 ),
#             )

#     return agent


# def _name_taken(
#     db: Session,
#     client_id: uuid.UUID,
#     name: str,
#     exclude_agent_id: uuid.UUID | None = None,
# ) -> bool:

#     query = (
#         db.query(Agent)
#         .filter(
#             Agent.client_id == client_id,
#             Agent.name.ilike(name),
#         )
#     )

#     if exclude_agent_id:

#         query = query.filter(
#             Agent.id != exclude_agent_id
#         )

#     return query.first() is not None


# def _resolve_client_id(
#     db: Session,
#     requested_client_id: uuid.UUID | None,
#     current_user: User,
# ) -> uuid.UUID:

#     # --------------------------------------------------------
#     # SUPERADMIN
#     # --------------------------------------------------------

#     if _is_super(current_user):

#         if requested_client_id is None:

#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail=(
#                     "Superadmin must provide client_id"
#                 ),
#             )

#         client = (
#             db.query(Client)
#             .filter(
#                 Client.id
#                 == requested_client_id
#             )
#             .first()
#         )

#         if not client:

#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Client not found",
#             )

#         return requested_client_id

#     # --------------------------------------------------------
#     # ADMIN
#     # --------------------------------------------------------

#     if current_user.client_id is None:

#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=(
#                 "Your account is not associated "
#                 "with an organization"
#             ),
#         )

#     if (
#         requested_client_id is not None
#         and requested_client_id
#         != current_user.client_id
#     ):

#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail=(
#                 "You can create agents only "
#                 "in your own organization"
#             ),
#         )

#     return current_user.client_id


# def _function_name(
#     db: Session,
#     client_id: uuid.UUID,
#     requested_name: str,
#     backend_type: str,
#     taken: set[str],
# ) -> str:

#     base_name = requested_name.strip()

#     if not base_name:

#         base_name = TYPE_INFO[
#             backend_type
#         ][0]

#     candidate = base_name
#     counter = 2

#     while True:

#         if candidate.lower() not in taken:

#             exists = (
#                 db.query(AgentFunction)
#                 .filter(
#                     AgentFunction.client_id
#                     == client_id,
#                     AgentFunction.name.ilike(
#                         candidate
#                     ),
#                 )
#                 .first()
#             )

#             if not exists:

#                 taken.add(
#                     candidate.lower()
#                 )

#                 return candidate

#         candidate = (
#             f"{base_name} {counter}"
#         )

#         counter += 1


# def _next_default_name(
#     db: Session,
#     client_id: uuid.UUID,
# ) -> str:

#     if not _name_taken(
#         db,
#         client_id,
#         DEFAULT_AGENT_NAME,
#     ):

#         return DEFAULT_AGENT_NAME

#     counter = 2

#     while True:

#         candidate = (
#             f"{DEFAULT_AGENT_NAME} "
#             f"{counter}"
#         )

#         if not _name_taken(
#             db,
#             client_id,
#             candidate,
#         ):

#             return candidate

#         counter += 1


# # ============================================================
# # CREATE COMPLETE AGENT
# #
# # POST /api/v1/agents
# # ============================================================

# @router.post(
#     "",
#     response_model=AgentResponse,
#     status_code=status.HTTP_201_CREATED,
# )
# def create_agent(
#     request: AgentCreateRequest,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(
#         admin_or_super
#     ),
# ):

#     # ========================================================
#     # 1. ORGANIZATION
#     # ========================================================

#     client_id = _resolve_client_id(
#         db,
#         request.client_id,
#         current_user,
#     )

#     # ========================================================
#     # 2. NAME
#     # ========================================================

#     if request.name is None:

#         name = _next_default_name(
#             db,
#             client_id,
#         )

#     else:

#         name = request.name.strip()

#         if _name_taken(
#             db,
#             client_id,
#             name,
#         ):

#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Agent name already exists",
#             )

#     # ========================================================
#     # 3. KNOWLEDGE BASE
#     # ========================================================

#     kb = request.knowledge_base

#     if (
#         kb.enabled
#         and kb.knowledge_base_ids
#     ):

#         found = {
#             item_id
#             for (item_id,) in (
#                 db.query(
#                     KnowledgeBase.id
#                 )
#                 .filter(
#                     KnowledgeBase.id.in_(
#                         kb.knowledge_base_ids
#                     )
#                 )
#                 .all()
#             )
#         }

#         missing = [
#             str(item_id)
#             for item_id
#             in kb.knowledge_base_ids
#             if item_id not in found
#         ]

#         if missing:

#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=(
#                     "Knowledge base not found: "
#                     + ", ".join(missing)
#                 ),
#             )

#     # ========================================================
#     # 4. FUNCTIONS
#     # ========================================================

#     function_rows = []

#     taken_function_names: set[str] = set()

#     for index, function_item in enumerate(
#         request.functions
#     ):

#         try:

#             backend_type = (
#                 function_item.backend_type
#             )

#             backend_config = (
#                 function_item.backend_config()
#             )

#             config = validate_config(
#                 backend_type,
#                 backend_config,
#             )

#         except ValidationError as exc:

#             errors = []

#             for error in exc.errors():

#                 errors.append(
#                     {
#                         "loc": [
#                             "body",
#                             "functions",
#                             index,
#                             "configuration",
#                             *error["loc"],
#                         ],
#                         "msg": error["msg"],
#                         "type": error["type"],
#                     }
#                 )

#             raise HTTPException(
#                 status_code=(
#                     status.HTTP_422_UNPROCESSABLE_ENTITY
#                 ),
#                 detail=errors,
#             )

#         function_name = _function_name(
#             db,
#             client_id,
#             function_item.name,
#             backend_type,
#             taken_function_names,
#         )

#         description = (
#             function_item.description.strip()
#         )

#         if not description:

#             description = TYPE_INFO[
#                 backend_type
#             ][1]

#         function_row = AgentFunction(
#             client_id=client_id,
#             name=function_name,
#             description=description,
#             type=backend_type,
#             config=config,
#             enabled=function_item.enabled,
#         )

#         function_rows.append(
#             function_row
#         )

#     # ========================================================
#     # 5. AGENT DATABASE DATA
#     # ========================================================

#     agent_data = (
#         request.to_agent_columns()
#     )

#     # ========================================================
#     # 6. SAVE EVERYTHING
#     # ========================================================

#     try:

#         db.add_all(
#             function_rows
#         )

#         db.flush()

#         function_json = [
#             {
#                 "id": str(
#                     function_row.id
#                 ),
#                 "type": function_row.type,
#                 "name": function_row.name,
#                 "enabled": function_row.enabled,
#             }
#             for function_row
#             in function_rows
#         ]

#         agent = Agent(
#             name=name,
#             client_id=client_id,
#             functions=function_json,
#             **agent_data,
#         )

#         db.add(agent)

#         db.commit()

#     except IntegrityError:

#         db.rollback()

#         raise HTTPException(
#             status_code=status.HTTP_409_CONFLICT,
#             detail=(
#                 "Agent or function name was "
#                 "taken at the same time. "
#                 "Please retry."
#             ),
#         )

#     db.refresh(agent)

#     return _to_response(
#         agent,
#         total_calls=0,
#     )


# # ============================================================
# # LIST
# #
# # GET /api/v1/agents
# # ============================================================

# @router.get(
#     "",
#     response_model=AgentListResponse,
# )
# def list_agents(
#     db: Session = Depends(get_db),
#     current_user: User = Depends(
#         admin_or_super
#     ),
#     status_filter: AgentStatus | None = Query(
#         default=None,
#         alias="status",
#     ),
# ):

#     query = db.query(Agent)

#     if not _is_super(current_user):

#         if current_user.client_id is None:

#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail=(
#                     "Your account is not associated "
#                     "with an organization"
#                 ),
#             )

#         query = query.filter(
#             Agent.client_id
#             == current_user.client_id
#         )

#     if status_filter is not None:

#         query = query.filter(
#             Agent.status
#             == status_filter
#         )

#     agents = (
#         query
#         .order_by(
#             Agent.created_at.desc()
#         )
#         .all()
#     )

#     items = []

#     for agent in agents:

#         items.append(
#             AgentSummary(
#                 id=agent.id,
#                 name=agent.name,
#                 status=agent.status,
#                 client_id=agent.client_id,
#                 total_calls=_call_count(
#                     db,
#                     agent.id,
#                 ),
#                 created_at=agent.created_at,
#                 updated_at=agent.updated_at,
#             )
#         )

#     return AgentListResponse(
#         items=items,
#         total=len(items),
#     )


# # ============================================================
# # GET
# #
# # GET /api/v1/agents/{agent_id}
# # ============================================================

# @router.get(
#     "/{agent_id}",
#     response_model=AgentResponse,
# )
# def get_agent(
#     agent_id: uuid.UUID,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(
#         admin_or_super
#     ),
# ):

#     agent = _get_agent_or_404(
#         db,
#         agent_id,
#         current_user,
#     )

#     return _to_response(
#         agent,
#         _call_count(
#             db,
#             agent.id,
#         ),
#     )


# # ============================================================
# # UPDATE
# #
# # PATCH /api/v1/agents/{agent_id}
# # ============================================================

# @router.patch(
#     "/{agent_id}",
#     response_model=AgentResponse,
# )
# def update_agent(
#     agent_id: uuid.UUID,
#     request: AgentUpdateRequest,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(
#         admin_or_super
#     ),
# ):

#     agent = _get_agent_or_404(
#         db,
#         agent_id,
#         current_user,
#     )

#     changes = request.model_dump(
#         exclude_unset=True
#     )

#     # --------------------------------------------------------
#     # NAME
#     # --------------------------------------------------------

#     if "name" in changes:

#         new_name = changes["name"]

#         if new_name is None:

#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Agent name cannot be null",
#             )

#         new_name = new_name.strip()

#         if not new_name:

#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Agent name cannot be empty",
#             )

#         if _name_taken(
#             db,
#             agent.client_id,
#             new_name,
#             exclude_agent_id=agent.id,
#         ):

#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Agent name already exists",
#             )

#         changes["name"] = new_name

#     # --------------------------------------------------------
#     # CLIENT
#     # --------------------------------------------------------

#     if "client_id" in changes:

#         requested_client_id = (
#             changes["client_id"]
#         )

#         if not _is_super(current_user):

#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail=(
#                     "Only superadmin can change "
#                     "an agent organization"
#                 ),
#             )

#         if requested_client_id is None:

#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="client_id cannot be null",
#             )

#         client = (
#             db.query(Client)
#             .filter(
#                 Client.id
#                 == requested_client_id
#             )
#             .first()
#         )

#         if not client:

#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="Client not found",
#             )

#     # --------------------------------------------------------
#     # APPLY CHANGES
#     # --------------------------------------------------------

#     for field, value in changes.items():

#         setattr(
#             agent,
#             field,
#             value,
#         )

#     try:

#         db.commit()

#     except IntegrityError:

#         db.rollback()

#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Unable to update agent",
#         )

#     db.refresh(agent)

#     return _to_response(
#         agent,
#         _call_count(
#             db,
#             agent.id,
#         ),
#     )


# # ============================================================
# # DELETE
# #
# # DELETE /api/v1/agents/{agent_id}
# # ============================================================

# @router.delete(
#     "/{agent_id}",
# )
# def delete_agent(
#     agent_id: uuid.UUID,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(
#         admin_or_super
#     ),
# ):

#     agent = _get_agent_or_404(
#         db,
#         agent_id,
#         current_user,
#     )

#     call_count = _call_count(
#         db,
#         agent.id,
#     )

#     if call_count > 0:

#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=(
#                 "Cannot delete an agent "
#                 "with call history"
#             ),
#         )

#     try:

#         db.delete(agent)
#         db.commit()

#     except IntegrityError:

#         db.rollback()

#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Unable to delete agent",
#         )

#     return {
#         "success": True,
#         "message": "Agent deleted successfully",
#         "id": str(agent_id),
#     }

import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db

from app.models.agent import Agent
from app.models.call import Call
from app.models.client import Client
from app.models.function import AgentFunction
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User, UserRole

from app.schemas.agent import (
    AgentCreateRequest,
    AgentListResponse,
    AgentResponse,
    AgentStatus,
    AgentSummary,
    AgentUpdateRequest,
    DEFAULT_AGENT_NAME,
)

from app.schemas.function import (
    TYPE_INFO,
    validate_config,
)

from app.api.dependencies import require_role


router = APIRouter(
    prefix="/agents",
    tags=["Agents"],
)


# ============================================================
# ROLE
# ============================================================

admin_or_super = require_role(
    UserRole.ADMIN,
    UserRole.SUPERADMIN,
)


# ============================================================
# HELPERS
# ============================================================

def _is_super(
    current_user: User,
) -> bool:

    return current_user.role == UserRole.SUPERADMIN.value


def _call_count(
    db: Session,
    agent_id: uuid.UUID,
) -> int:

    return (
        db.query(Call)
        .filter(
            Call.agent_id == agent_id
        )
        .count()
    )


def _to_response(
    agent: Agent,
    total_calls: int = 0,
) -> AgentResponse:

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        status=agent.status,
        client_id=agent.client_id,

        system_prompt=agent.system_prompt,
        welcome_message=agent.welcome_message,
        llm_model=agent.llm_model,
        voice=agent.voice,
        memory_enabled=agent.memory_enabled,
        emotion=agent.emotion,
        accent=agent.accent,
        timezone=agent.timezone,

        functions=agent.functions or [],
        calendars=agent.calendars or [],
        knowledge_base=agent.knowledge_base or [],
        crm_sync=agent.crm_sync or {},
        speech_settings=agent.speech_settings or {},
        call_settings=agent.call_settings or {},
        post_call_extraction=(
            agent.post_call_extraction or {}
        ),
        webhook_settings=(
            agent.webhook_settings or {}
        ),
        prompt_variables=(
            agent.prompt_variables or {}
        ),
        agent_metadata=(
            agent.agent_metadata or {}
        ),

        total_calls=total_calls,

        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _get_agent_or_404(
    db: Session,
    agent_id: uuid.UUID,
    current_user: User,
) -> Agent:

    agent = (
        db.query(Agent)
        .filter(
            Agent.id == agent_id
        )
        .first()
    )

    if not agent:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    if not _is_super(current_user):

        if (
            agent.client_id
            != current_user.client_id
        ):

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You can access agents only "
                    "in your own organization"
                ),
            )

    return agent


def _name_taken(
    db: Session,
    client_id: uuid.UUID,
    name: str,
    exclude_agent_id: uuid.UUID | None = None,
) -> bool:

    query = (
        db.query(Agent)
        .filter(
            Agent.client_id == client_id,
            Agent.name.ilike(name),
        )
    )

    if exclude_agent_id:

        query = query.filter(
            Agent.id != exclude_agent_id
        )

    return query.first() is not None


def _resolve_client_id(
    db: Session,
    requested_client_id: uuid.UUID | None,
    current_user: User,
) -> uuid.UUID:

    # --------------------------------------------------------
    # SUPERADMIN
    # --------------------------------------------------------

    if _is_super(current_user):

        if requested_client_id is None:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Superadmin must provide client_id"
                ),
            )

        client = (
            db.query(Client)
            .filter(
                Client.id
                == requested_client_id
            )
            .first()
        )

        if not client:

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )

        return requested_client_id

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if current_user.client_id is None:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Your account is not associated "
                "with an organization"
            ),
        )

    if (
        requested_client_id is not None
        and requested_client_id
        != current_user.client_id
    ):

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can create agents only "
                "in your own organization"
            ),
        )

    return current_user.client_id


def _function_name(
    db: Session,
    client_id: uuid.UUID,
    requested_name: str,
    backend_type: str,
    taken: set[str],
) -> str:

    base_name = requested_name.strip()

    if not base_name:

        base_name = TYPE_INFO[
            backend_type
        ][0]

    candidate = base_name
    counter = 2

    while True:

        if candidate.lower() not in taken:

            exists = (
                db.query(AgentFunction)
                .filter(
                    AgentFunction.client_id
                    == client_id,
                    AgentFunction.name.ilike(
                        candidate
                    ),
                )
                .first()
            )

            if not exists:

                taken.add(
                    candidate.lower()
                )

                return candidate

        candidate = (
            f"{base_name} {counter}"
        )

        counter += 1


def _next_default_name(
    db: Session,
    client_id: uuid.UUID,
) -> str:

    if not _name_taken(
        db,
        client_id,
        DEFAULT_AGENT_NAME,
    ):

        return DEFAULT_AGENT_NAME

    counter = 2

    while True:

        candidate = (
            f"{DEFAULT_AGENT_NAME} "
            f"{counter}"
        )

        if not _name_taken(
            db,
            client_id,
            candidate,
        ):

            return candidate

        counter += 1


# ============================================================
# CREATE COMPLETE AGENT
#
# POST /api/v1/agents
# ============================================================

@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_agent(
    request: AgentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        admin_or_super
    ),
):

    # ========================================================
    # 1. ORGANIZATION
    # ========================================================

    client_id = _resolve_client_id(
        db,
        request.client_id,
        current_user,
    )

    # ========================================================
    # 2. NAME
    # ========================================================

    if request.name is None:

        name = _next_default_name(
            db,
            client_id,
        )

    else:

        name = request.name.strip()

        if _name_taken(
            db,
            client_id,
            name,
        ):

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent name already exists",
            )

    # ========================================================
    # 3. KNOWLEDGE BASE
    # ========================================================

    kb = request.knowledge_base

    if (
        kb.enabled
        and kb.knowledge_base_ids
    ):

        found = {
            item_id
            for (item_id,) in (
                db.query(
                    KnowledgeBase.id
                )
                .filter(
                    KnowledgeBase.id.in_(
                        kb.knowledge_base_ids
                    )
                )
                .all()
            )
        }

        missing = [
            str(item_id)
            for item_id
            in kb.knowledge_base_ids
            if item_id not in found
        ]

        if missing:

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Knowledge base not found: "
                    + ", ".join(missing)
                ),
            )

    # ========================================================
    # 4. FUNCTIONS
    # ========================================================

    function_rows = []

    taken_function_names: set[str] = set()

    for index, function_item in enumerate(
        request.functions
    ):

        try:

            backend_type = (
                function_item.backend_type
            )

            backend_config = (
                function_item.backend_config()
            )

            config = validate_config(
                backend_type,
                backend_config,
            )

        except ValidationError as exc:

            errors = []

            for error in exc.errors():

                errors.append(
                    {
                        "loc": [
                            "body",
                            "functions",
                            index,
                            "configuration",
                            *error["loc"],
                        ],
                        "msg": error["msg"],
                        "type": error["type"],
                    }
                )

            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=errors,
            )

        function_name = _function_name(
            db,
            client_id,
            function_item.name,
            backend_type,
            taken_function_names,
        )

        description = (
            function_item.description.strip()
        )

        if not description:

            description = TYPE_INFO[
                backend_type
            ][1]

        function_row = AgentFunction(
            client_id=client_id,
            name=function_name,
            description=description,
            type=backend_type,
            config=config,
            enabled=function_item.enabled,
        )

        function_rows.append(
            function_row
        )

    # ========================================================
    # 5. AGENT DATABASE DATA
    # ========================================================

    agent_data = (
        request.to_agent_columns()
    )

    # ========================================================
    # 6. SAVE EVERYTHING
    # ========================================================

    try:

        db.add_all(
            function_rows
        )

        db.flush()

        function_json = [
            {
                "id": str(
                    function_row.id
                ),
                "type": function_row.type,
                "name": function_row.name,
                "enabled": function_row.enabled,
            }
            for function_row
            in function_rows
        ]

        agent = Agent(
            name=name,
            client_id=client_id,
            functions=function_json,
            **agent_data,
        )

        db.add(agent)

        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Agent or function name was "
                "taken at the same time. "
                "Please retry."
            ),
        )

    db.refresh(agent)

    return _to_response(
        agent,
        total_calls=0,
    )


# ============================================================
# LIST
#
# GET /api/v1/agents
# ============================================================

@router.get(
    "",
    response_model=AgentListResponse,
)
def list_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        admin_or_super
    ),
    status_filter: AgentStatus | None = Query(
        default=None,
        alias="status",
    ),
):

    query = db.query(Agent)

    if not _is_super(current_user):

        if current_user.client_id is None:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Your account is not associated "
                    "with an organization"
                ),
            )

        query = query.filter(
            Agent.client_id
            == current_user.client_id
        )

    if status_filter is not None:

        query = query.filter(
            Agent.status
            == status_filter
        )

    agents = (
        query
        .order_by(
            Agent.created_at.desc()
        )
        .all()
    )

    items = []

    for agent in agents:

        items.append(
            AgentSummary(
                id=agent.id,
                name=agent.name,
                status=agent.status,
                client_id=agent.client_id,
                total_calls=_call_count(
                    db,
                    agent.id,
                ),
                created_at=agent.created_at,
                updated_at=agent.updated_at,
            )
        )

    return AgentListResponse(
        items=items,
        total=len(items),
    )


# ============================================================
# GET
#
# GET /api/v1/agents/{agent_id}
# ============================================================

@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
)
def get_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        admin_or_super
    ),
):

    agent = _get_agent_or_404(
        db,
        agent_id,
        current_user,
    )

    return _to_response(
        agent,
        _call_count(
            db,
            agent.id,
        ),
    )


# ============================================================
# UPDATE
#
# PATCH /api/v1/agents/{agent_id}
# ============================================================

@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
)
def update_agent(
    agent_id: uuid.UUID,
    request: AgentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        admin_or_super
    ),
):

    agent = _get_agent_or_404(
        db,
        agent_id,
        current_user,
    )

    changes = request.model_dump(
        exclude_unset=True
    )

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    if "name" in changes:

        new_name = changes["name"]

        if new_name is None:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent name cannot be null",
            )

        new_name = new_name.strip()

        if not new_name:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent name cannot be empty",
            )

        if _name_taken(
            db,
            agent.client_id,
            new_name,
            exclude_agent_id=agent.id,
        ):

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent name already exists",
            )

        changes["name"] = new_name

    # --------------------------------------------------------
    # CLIENT
    # --------------------------------------------------------

    if "client_id" in changes:

        requested_client_id = (
            changes["client_id"]
        )

        if (
            not _is_super(current_user)
            and requested_client_id == agent.client_id
        ):
            # Frontend sends the full form back; an unchanged
            # client_id is not an organization change.
            changes.pop("client_id")

        elif not _is_super(current_user):

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Only superadmin can change "
                    "an agent organization"
                ),
            )

        if requested_client_id is None:

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_id cannot be null",
            )

        client = (
            db.query(Client)
            .filter(
                Client.id
                == requested_client_id
            )
            .first()
        )

        if not client:

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )

    # --------------------------------------------------------
    # APPLY CHANGES
    # --------------------------------------------------------

    for field, value in changes.items():

        setattr(
            agent,
            field,
            value,
        )

    try:

        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to update agent",
        )

    db.refresh(agent)

    return _to_response(
        agent,
        _call_count(
            db,
            agent.id,
        ),
    )


# ============================================================
# DELETE
#
# DELETE /api/v1/agents/{agent_id}
# ============================================================

@router.delete(
    "/{agent_id}",
)
def delete_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        admin_or_super
    ),
):

    agent = _get_agent_or_404(
        db,
        agent_id,
        current_user,
    )

    call_count = _call_count(
        db,
        agent.id,
    )

    if call_count > 0:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot delete an agent "
                "with call history"
            ),
        )

    try:

        db.delete(agent)
        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to delete agent",
        )

    return {
        "success": True,
        "message": "Agent deleted successfully",
        "id": str(agent_id),
    }