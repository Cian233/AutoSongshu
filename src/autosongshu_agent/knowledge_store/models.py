from __future__ import annotations

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .chunking import normalize_text


class KnowledgeBaseDraft(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None

    @model_validator(mode="after")
    def normalize_fields(self) -> "KnowledgeBaseDraft":
        self.name = self.name.strip()
        self.description = (
            self.description.strip()
            if isinstance(self.description, str)
            else self.description
        )
        return self


class KnowledgeBaseUpdateDraft(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None

    @model_validator(mode="after")
    def normalize_fields(self) -> "KnowledgeBaseUpdateDraft":
        if isinstance(self.name, str):
            self.name = self.name.strip()
        if isinstance(self.description, str):
            self.description = self.description.strip()
        return self


class KnowledgeDocumentDraft(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source_type: str = Field(default="text")
    source: str | None = None

    @model_validator(mode="after")
    def normalize_fields(self) -> "KnowledgeDocumentDraft":
        self.title = self.title.strip()
        self.content = normalize_text(self.content)
        self.source_type = (self.source_type or "text").strip().lower() or "text"
        self.source = (
            self.source.strip() if isinstance(self.source, str) else self.source
        )
        return self


class Base(DeclarativeBase):
    pass


class KnowledgeBaseRow(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class KnowledgeDocumentRow(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(48), default="text")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str] = mapped_column(Text)
    content_preview: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content_text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_dim: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32))
