from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .auth import CurrentOwner, OwnerContext
from .db import get_db_session
from .repositories import AssistantRepository
from .schemas import AssistantCreate, AssistantRead, AssistantUpdate
from .services import AssistantNotFound, AssistantService


router = APIRouter(prefix="/assistants", tags=["assistants"])


def get_assistant_service(session: Session = Depends(get_db_session)) -> Generator[AssistantService, None, None]:
    yield AssistantService(AssistantRepository(session))


@router.post("", response_model=AssistantRead, status_code=status.HTTP_201_CREATED)
def create_assistant(
    payload: AssistantCreate,
    owner: OwnerContext = CurrentOwner,
    service: AssistantService = Depends(get_assistant_service),
) -> AssistantRead:
    return service.create(owner.owner_id, payload)


@router.get("", response_model=list[AssistantRead])
def list_assistants(
    owner: OwnerContext = CurrentOwner,
    service: AssistantService = Depends(get_assistant_service),
) -> list[AssistantRead]:
    return list(service.list(owner.owner_id))


@router.get("/{assistant_id}", response_model=AssistantRead)
def get_assistant(
    assistant_id: str,
    owner: OwnerContext = CurrentOwner,
    service: AssistantService = Depends(get_assistant_service),
) -> AssistantRead:
    try:
        from uuid import UUID

        return service.get(owner.owner_id, UUID(assistant_id))
    except (AssistantNotFound, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant not found") from exc


@router.patch("/{assistant_id}", response_model=AssistantRead)
def update_assistant(
    assistant_id: str,
    payload: AssistantUpdate,
    owner: OwnerContext = CurrentOwner,
    service: AssistantService = Depends(get_assistant_service),
) -> AssistantRead:
    try:
        from uuid import UUID

        return service.update(owner.owner_id, UUID(assistant_id), payload)
    except (AssistantNotFound, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant not found") from exc
