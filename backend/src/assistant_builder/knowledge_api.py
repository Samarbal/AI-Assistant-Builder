from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .auth import CurrentOwner, OwnerContext
from .extraction import InvalidDocument
from .knowledge_repository import KnowledgeNotFound, KnowledgeLimitReached, KnowledgeStateConflict
from .knowledge_service import KnowledgeService, KnowledgeNotReady
from .config import get_settings
from .storage import StorageUnavailable

router = APIRouter(prefix='/assistants/{assistant_id}/knowledge-files', tags=['knowledge'])


class KnowledgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assistant_id: UUID
    original_filename: str
    file_format: str
    size_bytes: int
    processing_state: str
    error_code: str | None
    created_at: datetime


class DownloadLink(BaseModel):
    download_url: str
    expires_in: int


def service(request: Request):
    factory = getattr(request.app.state, 'session_factory', None)
    storage = getattr(request.app.state, 'file_storage', None)
    if factory is None:
        raise HTTPException(503, 'Database unavailable')
    return KnowledgeService(factory, storage)


def translate(exc):
    if isinstance(exc, KnowledgeNotFound):
        return HTTPException(404, 'Assistant or knowledge file not found')
    if isinstance(exc, KnowledgeLimitReached):
        return HTTPException(409, 'Maximum five attached knowledge files; remove a file first')
    if isinstance(exc, KnowledgeStateConflict):
        return HTTPException(409, 'File operation expired or changed; review its status')
    if isinstance(exc, KnowledgeNotReady):
        return HTTPException(409, 'File is not available for download')
    if isinstance(exc, InvalidDocument):
        return HTTPException(422, 'Invalid, encrypted, empty, scanned or unsupported document; remove the failed attachment before retrying')
    return HTTPException(503, 'Upload unavailable; review file status before retrying')


ERRORS = (KnowledgeNotFound, KnowledgeLimitReached, KnowledgeStateConflict, KnowledgeNotReady, InvalidDocument, StorageUnavailable, SQLAlchemyError)


@router.post('', status_code=201, response_model=KnowledgeRead, openapi_extra={
    'requestBody': {'required': True, 'content': {'multipart/form-data': {'schema': {
        'type': 'object', 'required': ['file'], 'properties': {'file': {'type': 'string', 'format': 'binary'}}}}}}
})
async def upload(assistant_id: UUID, request: Request, owner: OwnerContext = CurrentOwner,
                 workflow: KnowledgeService = Depends(service)):
    # Auth dependency runs before parsing the untrusted multipart body.
    if workflow.storage is None:
        raise HTTPException(503, 'Storage is not configured')
    async with request.form(max_files=1, max_fields=0) as form:
        entries = list(form.multi_items())
        if len(entries) != 1 or entries[0][0] != 'file' or not isinstance(entries[0][1], UploadFile):
            raise HTTPException(422, 'Provide exactly one file and no additional fields')
        document = entries[0][1]
        name = (document.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
        if not name.strip() or len(name) > 255 or name.rsplit('.', 1)[-1].lower() not in ('pdf', 'docx'):
            raise HTTPException(422, 'Only PDF and DOCX filenames are supported')
        content = await document.read(10_000_001)
        if not content or len(content) > 10_000_000:
            raise HTTPException(413, 'File must contain 1 to 10000000 bytes')
        try:
            return await run_in_threadpool(workflow.upload, owner.owner_id, assistant_id, name, content)
        except ERRORS as exc:
            raise translate(exc) from None


@router.get('', response_model=list[KnowledgeRead])
def list_files(assistant_id: UUID, owner: OwnerContext = CurrentOwner, workflow=Depends(service)):
    try:
        return workflow.list(owner.owner_id, assistant_id)
    except ERRORS as exc:
        raise translate(exc) from None


@router.delete('/{file_id}', status_code=204)
def remove_file(assistant_id: UUID, file_id: UUID, owner: OwnerContext = CurrentOwner, workflow=Depends(service)):
    try:
        workflow.remove(owner.owner_id, assistant_id, file_id)
        return Response(status_code=204)
    except ERRORS as exc:
        raise translate(exc) from None


@router.post('/{file_id}/download-url', response_model=DownloadLink)
def download_file(assistant_id: UUID, file_id: UUID, response: Response,
                  owner: OwnerContext = CurrentOwner, workflow=Depends(service)):
    expires_in = get_settings().storage_signed_url_seconds
    try:
        url = workflow.download_url(owner.owner_id, assistant_id, file_id, expires_in)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        return DownloadLink(download_url=url, expires_in=expires_in)
    except ERRORS as exc:
        raise translate(exc) from None
