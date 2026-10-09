from collections.abc import Sequence
from uuid import UUID

from .models import Assistant
from .repositories import AssistantRepository
from .schemas import AssistantCreate, AssistantUpdate


class AssistantNotFound(Exception):
    pass


class AssistantService:
    """Application use cases; owner identity is always supplied by the auth boundary."""

    def __init__(self, repository: AssistantRepository):
        self.repository = repository

    def create(self, owner_id: UUID, data: AssistantCreate) -> Assistant:
        return self.repository.create(owner_id, data)

    def list(self, owner_id: UUID) -> Sequence[Assistant]:
        return self.repository.list_for_owner(owner_id)

    def get(self, owner_id: UUID, assistant_id: UUID) -> Assistant:
        assistant = self.repository.get_for_owner(owner_id, assistant_id)
        if assistant is None:
            raise AssistantNotFound
        return assistant

    def update(self, owner_id: UUID, assistant_id: UUID, data: AssistantUpdate) -> Assistant:
        assistant = self.get(owner_id, assistant_id)
        return self.repository.update(assistant, data)
