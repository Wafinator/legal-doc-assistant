"""REST endpoints for uploading, listing and fetching documents."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.documents import repository
from app.schemas import DocumentCreate, DocumentList, DocumentRead, DocumentSummary

router = APIRouter(prefix="/documents", tags=["documents"])

# A reusable alias: any endpoint parameter typed `DbSession` gets a session injected.
DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(body: DocumentCreate, db: DbSession) -> DocumentRead:
    doc = repository.create_document(db, title=body.title, content=body.content)
    return DocumentRead.model_validate(doc)


@router.get("", response_model=DocumentList)
def list_documents(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    rows, total = repository.list_documents(db, limit=limit, offset=offset)
    return DocumentList(
        items=[DocumentSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: int, db: DbSession) -> DocumentRead:
    doc = repository.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentRead.model_validate(doc)
