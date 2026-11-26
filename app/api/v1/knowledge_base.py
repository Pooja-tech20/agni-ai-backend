import logging
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_role
from app.db.session import get_db
from app.models.client import Client
from app.models.knowledge_base import KnowledgeBase, KnowledgeSource
from app.models.user import User, UserRole
from app.schemas.knowledge_base import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
    KnowledgeSourceCreateRequest,
    KnowledgeSourceListResponse,
    KnowledgeSourceResponse,
)
from app.services.knowledge.ingestion import (
    UPLOAD_ROOT,
    process_source_background,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Base"])
admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)
ALLOWED_FILE_EXTENSIONS = {".pdf", ".txt", ".docx", ".md"}
MAX_UPLOAD_SIZE = 20 * 1024 * 1024


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


def _resolve_client_id(
    db: Session, requested_client_id: uuid.UUID | None, user: User
) -> uuid.UUID:
    if _is_super(user):
        if requested_client_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Superadmin must provide client_id",
            )
        if db.get(Client, requested_client_id) is None:
            raise HTTPException(status_code=404, detail="Client not found")
        return requested_client_id

    if user.client_id is None:
        raise HTTPException(
            status_code=400,
            detail="Your account is not associated with an organization",
        )
    if requested_client_id is not None and requested_client_id != user.client_id:
        raise HTTPException(status_code=403, detail="You can manage knowledge bases only in your own organization")
    return user.client_id


def _get_knowledge_base(
    db: Session, knowledge_base_id: uuid.UUID, user: User
) -> KnowledgeBase:
    query = select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
    if not _is_super(user):
        if user.client_id is None:
            raise HTTPException(status_code=400, detail="Your account is not associated with an organization")
        query = query.where(KnowledgeBase.client_id == user.client_id)
    knowledge_base = db.scalar(query)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return knowledge_base

def _validate_ingestion_target(
    knowledge_base: KnowledgeBase,
) -> uuid.UUID:

    if knowledge_base.client_id is None:
        raise HTTPException(
            status_code=400,
            detail="Knowledge base must belong to an organization",
        )

    if knowledge_base.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Knowledge base is inactive",
        )

    return knowledge_base.client_id

def _validate_source_payload(payload: KnowledgeSourceCreateRequest) -> None:
    values = {"text": payload.content, "url": payload.url, "file": payload.file_name}
    selected = values[payload.source_type]
    if not selected or not str(selected).strip():
        raise HTTPException(status_code=400, detail=f"{payload.source_type.title()} source data is required")
    for kind, value in values.items():
        if kind != payload.source_type and value is not None:
            raise HTTPException(status_code=400, detail=f"Only {payload.source_type} source data may be provided")
    if payload.source_type == "url":
        parsed = urlparse(payload.url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=400, detail="URL must be a valid HTTP or HTTPS URL")


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    client_id = _resolve_client_id(db, payload.client_id, current_user)
    knowledge_base = KnowledgeBase(
        client_id=client_id,
        name=payload.name,
        description=payload.description,
        status="active",
    )
    db.add(knowledge_base)
    try:
        db.commit()
        db.refresh(knowledge_base)
    except Exception:
        db.rollback()
        raise
    return knowledge_base


@router.get("", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    query = select(KnowledgeBase)
    if not _is_super(current_user):
        if current_user.client_id is None:
            raise HTTPException(status_code=400, detail="Your account is not associated with an organization")
        query = query.where(KnowledgeBase.client_id == current_user.client_id)
    items = list(db.scalars(query.order_by(KnowledgeBase.created_at.desc())))
    return KnowledgeBaseListResponse(total=len(items), items=items)


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    return _get_knowledge_base(db, knowledge_base_id, current_user)


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeBaseUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    knowledge_base = _get_knowledge_base(db, knowledge_base_id, current_user)
    updates = payload.model_dump(exclude_unset=True)
    requested_client_id = updates.pop("client_id", None)
    if "client_id" in payload.model_fields_set:
        if not _is_super(current_user):
            raise HTTPException(status_code=403, detail="Only superadmin can assign knowledge-base ownership")
        if knowledge_base.client_id is not None:
            raise HTTPException(status_code=409, detail="Knowledge-base ownership cannot be transferred")
        if requested_client_id is None or db.get(Client, requested_client_id) is None:
            raise HTTPException(status_code=404, detail="Valid client_id is required")
        knowledge_base.client_id = requested_client_id
    for field, value in updates.items():
        setattr(knowledge_base, field, value)
    db.commit()
    db.refresh(knowledge_base)
    return knowledge_base


@router.delete("/{knowledge_base_id}", status_code=status.HTTP_200_OK)
def delete_knowledge_base(
    knowledge_base_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    knowledge_base = _get_knowledge_base(db, knowledge_base_id, current_user)
    upload_directory = UPLOAD_ROOT / str(knowledge_base_id)
    db.delete(knowledge_base)
    db.commit()
    try:
        if upload_directory.exists():
            import shutil
            shutil.rmtree(upload_directory)
    except OSError:
        logger.exception("Could not remove uploaded files for knowledge base %s", knowledge_base_id)
    return {"success": True, "message": "Knowledge base deleted successfully"}



@router.post(
    "/{knowledge_base_id}/sources",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeSourceCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    knowledge_base = _get_knowledge_base(
        db,
        knowledge_base_id,
        current_user,
    )

    client_id = _validate_ingestion_target(
        knowledge_base
    )

    _validate_source_payload(payload)

    source = KnowledgeSource(
        id=uuid.uuid4(),
        knowledge_base_id=knowledge_base_id,
        title=payload.title,
        source_type=payload.source_type,
        content=payload.content,
        url=payload.url,
        file_name=(
            Path(payload.file_name).name
            if payload.file_name
            else None
        ),
        file_size=payload.file_size,
        status="active",
        processing_status="pending",
        processing_error=None,
        chunk_count=0,
    )

    # File metadata alone does not contain document data.
    if payload.source_type == "file":
        source.processing_status = "failed"
        source.processing_error = (
            "File content is missing. "
            "Use the file upload endpoint."
        )

    db.add(source)

    try:
        db.commit()
        db.refresh(source)

    except Exception:
        db.rollback()
        raise

    if payload.source_type in {"text", "url"}:

        background_tasks.add_task(
            process_source_background,
            source.id,
            client_id,
        )

    return source




@router.post(
    "/{knowledge_base_id}/sources/upload",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_source(
    knowledge_base_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    knowledge_base = _get_knowledge_base(
        db,
        knowledge_base_id,
        current_user,
    )

    client_id = _validate_ingestion_target(
        knowledge_base
    )

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="File name is required",
        )

    original_filename = Path(file.filename).name
    extension = Path(original_filename).suffix.lower()

    if extension not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. "
                "Allowed types: PDF, TXT, DOCX, MD"
            ),
        )

    source = KnowledgeSource(
        id=uuid.uuid4(),
        knowledge_base_id=knowledge_base_id,
        title=Path(original_filename).stem,
        source_type="file",
        file_name=original_filename,
        file_size=0,
        status="active",
        processing_status="pending",
        processing_error=None,
        chunk_count=0,
    )

    stored_path = (
        UPLOAD_ROOT
        / str(knowledge_base_id)
        / f"{source.id}{extension}"
    )

    total_size = 0

    try:

        db.add(source)
        db.flush()

        stored_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with stored_path.open("wb") as destination:

            while chunk := file.file.read(1024 * 1024):

                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the 20 MB upload limit",
                    )

                destination.write(chunk)

        if total_size == 0:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty",
            )

        source.file_size = total_size

        db.commit()

    except HTTPException:

        db.rollback()
        stored_path.unlink(missing_ok=True)
        raise

    except Exception:

        db.rollback()
        stored_path.unlink(missing_ok=True)

        logger.exception(
            "Knowledge source upload failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to upload file",
        )

    finally:

        file.file.close()

    db.refresh(source)

    background_tasks.add_task(
        process_source_background,
        source.id,
        client_id,
    )

    return source



@router.get("/{knowledge_base_id}/sources", response_model=KnowledgeSourceListResponse)
def list_sources(
    knowledge_base_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    _get_knowledge_base(db, knowledge_base_id, current_user)
    items = list(db.scalars(
        select(KnowledgeSource)
        .where(KnowledgeSource.knowledge_base_id == knowledge_base_id)
        .order_by(KnowledgeSource.created_at.desc())
    ))
    return KnowledgeSourceListResponse(total=len(items), items=items)


@router.get("/{knowledge_base_id}/sources/{source_id}", response_model=KnowledgeSourceResponse)
def get_source(
    knowledge_base_id: uuid.UUID,
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    _get_knowledge_base(db, knowledge_base_id, current_user)
    source = db.scalar(select(KnowledgeSource).where(
        KnowledgeSource.id == source_id,
        KnowledgeSource.knowledge_base_id == knowledge_base_id,
    ))
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    return source


@router.delete("/{knowledge_base_id}/sources/{source_id}", status_code=status.HTTP_200_OK)
def delete_source(
    knowledge_base_id: uuid.UUID,
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    _get_knowledge_base(db, knowledge_base_id, current_user)
    source = db.scalar(select(KnowledgeSource).where(
        KnowledgeSource.id == source_id,
        KnowledgeSource.knowledge_base_id == knowledge_base_id,
    ))
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    file_paths = list((UPLOAD_ROOT / str(knowledge_base_id)).glob(f"{source.id}.*")) if source.source_type == "file" else []
    db.delete(source)
    db.commit()
    for file_path in file_paths:
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove uploaded source file %s", file_path)
    return {"success": True, "message": "Knowledge source deleted successfully", "id": str(source_id)}


@router.post(
    "/{knowledge_base_id}/sources/{source_id}/reprocess",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reprocess_source(
    knowledge_base_id: uuid.UUID,
    source_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    knowledge_base = _get_knowledge_base(
        db,
        knowledge_base_id,
        current_user,
    )

    client_id = _validate_ingestion_target(
        knowledge_base
    )

    source = db.scalar(
        select(KnowledgeSource)
        .where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.knowledge_base_id
            == knowledge_base_id,
        )
        .with_for_update()
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Knowledge source not found",
        )

    if source.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Knowledge source is inactive",
        )

    if source.processing_status == "processing":
        raise HTTPException(
            status_code=409,
            detail="Knowledge source is already processing",
        )

    if source.source_type == "file":

        extension = Path(
            source.file_name or ""
        ).suffix.lower()

        stored_path = (
            UPLOAD_ROOT
            / str(knowledge_base_id)
            / f"{source.id}{extension}"
        )

        if not stored_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="Source file is missing. Upload it again.",
            )

    source.processing_status = "pending"
    source.processing_error = None

    try:
        db.commit()
        db.refresh(source)

    except Exception:
        db.rollback()
        raise

    background_tasks.add_task(
        process_source_background,
        source.id,
        client_id,
    )

    return source
