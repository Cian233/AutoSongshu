from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Boolean, String, Text, create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import load_project_env
from .utils import now_iso


def _normalize_allowed_hosts(raw_hosts: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_hosts:
        value = item.strip().lower()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


class AuthorizationDraft(BaseModel):
    name: str = Field(min_length=1)
    authorization: str = Field(min_length=1)
    start_url: str
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_subdomains: bool = True
    notes: str | None = None

    @model_validator(mode="after")
    def infer_allowed_hosts(self) -> "AuthorizationDraft":
        self.allowed_hosts = _normalize_allowed_hosts(self.allowed_hosts)
        if not self.allowed_hosts:
            parsed = urlparse(self.start_url)
            if parsed.hostname:
                self.allowed_hosts = [parsed.hostname.lower()]
        return self


class AuthorizationRecord(AuthorizationDraft):
    id: str
    created_at: str
    updated_at: str


class Base(DeclarativeBase):
    pass


class AuthorizationRow(Base):
    __tablename__ = "authorization_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    authorization: Mapped[str] = mapped_column(String(255))
    start_url: Mapped[str] = mapped_column(Text)
    allowed_hosts_json: Mapped[str] = mapped_column(Text, default="[]")
    allow_subdomains: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class AuthorizationStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        load_project_env(self.project_root)
        self.lock = threading.RLock()
        self.legacy_json_path = self.project_root / "data" / "authorizations.json"
        self.database_url = self._resolve_database_url()
        self.engine = self._create_engine()
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        self._migrate_legacy_json_if_needed()

    def _resolve_database_url(self) -> str:
        raw_url = (
            os.getenv("AUTOSONGSHU_AUTH_DATABASE_URL")
            or os.getenv("AUTOSONGSHU_DATABASE_URL")
            or f"sqlite:///{(self.project_root / 'data' / 'autosongshu.db').resolve().as_posix()}"
        )
        url = make_url(raw_url)
        if (
            url.drivername.startswith("sqlite")
            and url.database
            and url.database != ":memory:"
        ):
            database_path = Path(url.database)
            if not database_path.is_absolute():
                database_path = (self.project_root / database_path).resolve()
            database_path.parent.mkdir(parents=True, exist_ok=True)
            url = url.set(database=str(database_path))
            return url.render_as_string(hide_password=False)
        return raw_url

    def _create_engine(self) -> Engine:
        connect_args: dict[str, object] = {}
        if self.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        return create_engine(self.database_url, connect_args=connect_args)

    def _row_to_record(self, row: AuthorizationRow) -> AuthorizationRecord:
        try:
            allowed_hosts = json.loads(row.allowed_hosts_json)
        except Exception:
            allowed_hosts = []
        return AuthorizationRecord(
            id=row.id,
            name=row.name,
            authorization=row.authorization,
            start_url=row.start_url,
            allowed_hosts=allowed_hosts,
            allow_subdomains=row.allow_subdomains,
            notes=row.notes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _migrate_legacy_json_if_needed(self) -> None:
        if not self.legacy_json_path.exists():
            return
        with self.session_factory() as session:
            existing = session.scalar(select(AuthorizationRow.id).limit(1))
            if existing is not None:
                return
            try:
                payload = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
            except Exception:
                return
            if not isinstance(payload, list):
                return
            rows: list[AuthorizationRow] = []
            for item in payload:
                try:
                    record = AuthorizationRecord.model_validate(item)
                except Exception:
                    continue
                rows.append(
                    AuthorizationRow(
                        id=record.id,
                        name=record.name,
                        authorization=record.authorization,
                        start_url=record.start_url,
                        allowed_hosts_json=json.dumps(
                            record.allowed_hosts, ensure_ascii=False
                        ),
                        allow_subdomains=record.allow_subdomains,
                        notes=record.notes,
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    ),
                )
            if rows:
                session.add_all(rows)
                session.commit()
                migrated_path = self.legacy_json_path.with_suffix(".json.migrated")
                try:
                    self.legacy_json_path.replace(migrated_path)
                except Exception:
                    pass

    def list_records(self) -> list[dict[str, str | bool | list[str] | None]]:
        with self.lock, self.session_factory() as session:
            rows = session.scalars(
                select(AuthorizationRow).order_by(AuthorizationRow.updated_at.desc())
            ).all()
        return [self._row_to_record(row).model_dump(mode="json") for row in rows]

    def create_record(
        self, payload: AuthorizationDraft
    ) -> dict[str, str | bool | list[str] | None]:
        timestamp = now_iso()
        record = AuthorizationRecord(
            id=uuid4().hex,
            created_at=timestamp,
            updated_at=timestamp,
            **payload.model_dump(mode="python"),
        )
        with self.lock, self.session_factory() as session:
            row = AuthorizationRow(
                id=record.id,
                name=record.name,
                authorization=record.authorization,
                start_url=record.start_url,
                allowed_hosts_json=json.dumps(record.allowed_hosts, ensure_ascii=False),
                allow_subdomains=record.allow_subdomains,
                notes=record.notes,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            session.add(row)
            session.commit()
        return record.model_dump(mode="json")

    def close(self) -> None:
        self.engine.dispose()
