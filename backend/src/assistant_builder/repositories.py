# طبقة الوصول للبيانات 

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Assistant
from .schemas import AssistantCreate, AssistantUpdate


class AssistantRepository:
    """Persistence boundary. Every method requires the authenticated owner ID."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, owner_id: UUID, data: AssistantCreate) -> Assistant:
        assistant = Assistant(owner_id=owner_id, **data.model_dump())
        self.session.add(assistant)
        self.session.flush()
        return assistant

    def list_for_owner(self, owner_id: UUID) -> Sequence[Assistant]:
        statement = select(Assistant).where(Assistant.owner_id == owner_id).order_by(Assistant.created_at)
        return self.session.scalars(statement).all()

    def get_for_owner(self, owner_id: UUID, assistant_id: UUID) -> Assistant | None:
        statement = select(Assistant).where(
            Assistant.owner_id == owner_id,
            Assistant.id == assistant_id,
        )
        return self.session.scalar(statement)

    def update(self, assistant: Assistant, data: AssistantUpdate) -> Assistant:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(assistant, field, value)
        self.session.flush()
        return assistant
