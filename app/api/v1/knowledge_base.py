import uuid

from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase, KnowledgeSource
from app.schemas.knowledge_base import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
    KnowledgeSourceCreateRequest,
    KnowledgeSourceListResponse,
    KnowledgeSourceResponse,
)

router = APIRouter(
    prefix="/knowledge-bases",
    tags=["Knowledge Base"],
)
ALLOWED_FILE_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".docx",
    ".md",
}


# ============================================================
# KNOWLEDGE BASE
# ============================================================

@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    db: Session = Depends(get_db),
):
    knowledge_base = KnowledgeBase(
        name=payload.name,
        description=payload.description,
        status="active",
    )

    db.add(knowledge_base)
    db.commit()
    db.refresh(knowledge_base)

    return knowledge_base


@router.get(
    "",
    response_model=KnowledgeBaseListResponse,
)
def list_knowledge_bases(
    db: Session = Depends(get_db),
):
    items = list(
        db.scalars(
            select(KnowledgeBase).order_by(
                KnowledgeBase.created_at.desc()
            )
        )
    )

    return KnowledgeBaseListResponse(
        total=len(items),
        items=items,
    )


@router.get(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)

    if knowledge_base is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    return knowledge_base


@router.patch(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
def update_knowledge_base(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeBaseUpdateRequest,
    db: Session = Depends(get_db),
):
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)

    if knowledge_base is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    updates = payload.model_dump(exclude_unset=True)

    for field, value in updates.items():
        setattr(knowledge_base, field, value)

    db.commit()
    db.refresh(knowledge_base)

    return knowledge_base


@router.delete(
    "/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_knowledge_base(
    knowledge_base_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)

    if knowledge_base is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    db.delete(knowledge_base)
    db.commit()

    return None


# ============================================================
# KNOWLEDGE SOURCES
# ============================================================

@router.post(
    "/{knowledge_base_id}/sources",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeSourceCreateRequest,
    db: Session = Depends(get_db),
):
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)

    if knowledge_base is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    if payload.source_type == "text" and not payload.content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content is required for text sources",
        )

    if payload.source_type == "url" and not payload.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL is required for URL sources",
        )

    if payload.source_type == "file" and not payload.file_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required for file sources",
        )

    source = KnowledgeSource(
        knowledge_base_id=knowledge_base_id,
        title=payload.title,
        source_type=payload.source_type,
        content=payload.content,
        url=payload.url,
        file_name=payload.file_name,
        file_size=payload.file_size,
        status="active",
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    return source

@router.post(
    "/{knowledge_base_id}/sources/upload",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_source(
    knowledge_base_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # --------------------------------------------------------
    # 1. Check knowledge base
    # --------------------------------------------------------
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)

    if knowledge_base is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    # --------------------------------------------------------
    # 2. Validate filename
    # --------------------------------------------------------
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required",
        )

    original_filename = Path(file.filename).name
    extension = Path(original_filename).suffix.lower()

    # --------------------------------------------------------
    # 3. Validate file type
    # --------------------------------------------------------
    if extension not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported file type. "
                "Allowed types: PDF, TXT, DOCX, MD"
            ),
        )

    # --------------------------------------------------------
    # 4. Create source record
    # --------------------------------------------------------
    source = KnowledgeSource(
        knowledge_base_id=knowledge_base_id,
        title=Path(original_filename).stem,
        source_type="file",
        file_name=original_filename,
        file_size=0,
        status="active",
    )

    db.add(source)

    # Generate source ID before saving the file
    db.flush()

    # --------------------------------------------------------
    # 5. Create upload directory
    # --------------------------------------------------------
    upload_directory = (
        Path("uploads")
        / "knowledge_base"
        / str(knowledge_base_id)
    )

    upload_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # 6. Use source ID as stored filename
    # --------------------------------------------------------
    stored_filename = f"{source.id}{extension}"
    stored_path = upload_directory / stored_filename

    try:
        # ----------------------------------------------------
        # 7. Save file to disk
        # ----------------------------------------------------
        with stored_path.open("wb") as destination:
            shutil.copyfileobj(
                file.file,
                destination,
            )

        # ----------------------------------------------------
        # 8. Save actual file size
        # ----------------------------------------------------
        source.file_size = stored_path.stat().st_size

        # ----------------------------------------------------
        # 9. Commit database record
        # ----------------------------------------------------
        db.commit()
        db.refresh(source)

        return source

    except Exception:
        db.rollback()

        if stored_path.exists():
            stored_path.unlink()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file",
        )

    finally:
        file.file.close()

@router.get(
    "/{knowledge_base_id}/sources",
    response_model=KnowledgeSourceListResponse,
)
def list_sources(
    knowledge_base_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)

    if knowledge_base is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    items = list(
        db.scalars(
            select(KnowledgeSource)
            .where(
                KnowledgeSource.knowledge_base_id == knowledge_base_id
            )
            .order_by(KnowledgeSource.created_at.desc())
        )
    )

    return KnowledgeSourceListResponse(
        total=len(items),
        items=items,
    )


@router.get(
    "/{knowledge_base_id}/sources/{source_id}",
    response_model=KnowledgeSourceResponse,
)
def get_source(
    knowledge_base_id: uuid.UUID,
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    source = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.knowledge_base_id == knowledge_base_id,
        )
    )

    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge source not found",
        )

    return source


@router.delete(
    "/{knowledge_base_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_source(
    knowledge_base_id: uuid.UUID,
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    source = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.knowledge_base_id == knowledge_base_id,
        )
    )

    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge source not found",
        )

    db.delete(source)
    db.commit()

    return None