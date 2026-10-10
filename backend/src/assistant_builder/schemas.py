# شكل البيانات داحل ال api 
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssistantFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=500)
    colors: dict[str, str] = Field(default_factory=dict)
    response_style: str = Field(min_length=1, max_length=100)
    tone: str = Field(min_length=1, max_length=100)
    fallback_message: str = Field(min_length=1, max_length=500)


class AssistantCreate(AssistantFields):
    pass


class AssistantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null; omit it to keep the current value")
        return value

    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, min_length=1, max_length=500)
    colors: dict[str, str] | None = None
    response_style: str | None = Field(default=None, min_length=1, max_length=100)
    tone: str | None = Field(default=None, min_length=1, max_length=100)
    fallback_message: str | None = Field(default=None, min_length=1, max_length=500)


class AssistantRead(AssistantFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    state: str
    created_at: datetime
    updated_at: datetime
