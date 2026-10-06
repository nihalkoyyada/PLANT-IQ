"""SQLAlchemy models matching PostgreSQL schema for PlantIQ backend with full property backwards-compatibility."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4
from typing import Any, Dict, List, Optional
import json
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import (
    DOUBLE_PRECISION,
    JSONB,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class FlagsArray(TypeDecorator[List[str]]):
    """Platform-independent array of string flags (Postgres ARRAY(Text), SQLite JSON/Text)."""

    impl = ARRAY(Text)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Text())
        return dialect.type_descriptor(ARRAY(Text()))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            value = []
        if dialect.name == "sqlite":
            if isinstance(value, (list, tuple, set)):
                return json.dumps(list(value))
            return str(value)
        return list(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return []
        if dialect.name == "sqlite" and isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return []
        return list(value)



class Organization(Base):
    """Multi-tenant Organization entity."""

    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    users: Mapped[List["User"]] = relationship(
        "User", back_populates="organization", cascade="all, delete-orphan"
    )
    plants: Mapped[List["Plant"]] = relationship(
        "Plant", back_populates="organization", cascade="all, delete-orphan"
    )
    files: Mapped[List["File"]] = relationship(
        "File", back_populates="organization", cascade="all, delete-orphan"
    )
    mapping_templates: Mapped[List["MappingTemplate"]] = relationship(
        "MappingTemplate", back_populates="organization", cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs: Any) -> None:
        self._slug = kwargs.pop("slug", None)
        super().__init__(**kwargs)

    @property
    def slug(self) -> str:
        s = getattr(self, "_slug", None)
        if s:
            return s
        if not getattr(self, "name", None):
            return ""
        return self.name.lower().replace(" ", "-").replace("_", "-")

    @slug.setter
    def slug(self, value: str) -> None:
        self._slug = value


class User(Base):
    """User accounts belonging to an Organization."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="users")

    def __init__(self, **kwargs: Any) -> None:
        if "organization_id" in kwargs:
            kwargs["org_id"] = kwargs.pop("organization_id")
        if "hashed_password" in kwargs:
            kwargs["password_hash"] = kwargs.pop("hashed_password")
        kwargs.pop("is_superuser", None)
        if "role" not in kwargs:
            kwargs["role"] = "admin"
        super().__init__(**kwargs)

    @property
    def organization_id(self) -> UUID:
        return self.org_id

    @organization_id.setter
    def organization_id(self, value: UUID) -> None:
        self.org_id = value

    @property
    def hashed_password(self) -> str:
        return self.password_hash

    @hashed_password.setter
    def hashed_password(self, value: str) -> None:
        self.password_hash = value

    @property
    def is_superuser(self) -> bool:
        return self.role == "admin"

    @is_superuser.setter
    def is_superuser(self, value: bool) -> None:
        pass

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'engineer', 'viewer')",
            name="ck_users_role",
        ),
    )


class Plant(Base):
    """Power Plant entity."""

    __tablename__ = "plants"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    plant_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    capacity_ac_kw: Mapped[Optional[float]] = mapped_column(
        Numeric,
        nullable=True,
    )
    capacity_dc_kwp: Mapped[Optional[float]] = mapped_column(
        Numeric,
        nullable=True,
    )
    latitude: Mapped[Optional[float]] = mapped_column(
        DOUBLE_PRECISION,
        nullable=True,
    )
    longitude: Mapped[Optional[float]] = mapped_column(
        DOUBLE_PRECISION,
        nullable=True,
    )
    timezone: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="Asia/Kolkata",
    )
    cod_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
    )
    expected_pr: Mapped[float] = mapped_column(
        Numeric,
        nullable=False,
        server_default="0.80",
    )
    tariff_inr_per_kwh: Mapped[Optional[float]] = mapped_column(
        Numeric,
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="plants")
    assets: Mapped[List["Asset"]] = relationship("Asset", back_populates="plant", cascade="all, delete-orphan")
    kpi_values: Mapped[List["KPIValue"]] = relationship("KPIValue", back_populates="plant", cascade="all, delete-orphan")

    def __init__(self, **kwargs: Any) -> None:
        if "organization_id" in kwargs:
            kwargs["org_id"] = kwargs.pop("organization_id")
        if "metadata_json" in kwargs:
            kwargs["metadata_"] = kwargs.pop("metadata_json")
        self._slug = kwargs.pop("slug", None)
        super().__init__(**kwargs)

    @property
    def organization_id(self) -> UUID:
        return self.org_id

    @organization_id.setter
    def organization_id(self, value: UUID) -> None:
        self.org_id = value

    @property
    def slug(self) -> str:
        s = getattr(self, "_slug", None)
        if s:
            return s
        if not getattr(self, "name", None):
            return ""
        return self.name.lower().replace(" ", "-").replace("_", "-")

    @slug.setter
    def slug(self, value: str) -> None:
        self._slug = value

    @property
    def metadata_json(self) -> dict:
        return self.metadata_

    @metadata_json.setter
    def metadata_json(self, value: dict) -> None:
        self.metadata_ = value

    __table_args__ = (
        CheckConstraint(
            "plant_type IN ('solar', 'wind', 'process')",
            name="ck_plants_plant_type",
        ),
        UniqueConstraint(
            "org_id",
            "name",
            name="uq_plants_org_name",
        ),
    )


class Asset(Base):
    """Hierarchical Asset entity."""

    __tablename__ = "assets"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    plant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("plants.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    asset_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    make: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    model: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    rated_kw: Mapped[Optional[float]] = mapped_column(
        Numeric,
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        server_default="{}",
    )

    plant: Mapped["Plant"] = relationship("Plant", back_populates="assets")
    parent: Mapped[Optional["Asset"]] = relationship("Asset", remote_side=[id], back_populates="children")
    children: Mapped[List["Asset"]] = relationship("Asset", back_populates="parent", cascade="all, delete-orphan")
    channels: Mapped[List["Channel"]] = relationship("Channel", back_populates="asset", cascade="all, delete-orphan")
    kpi_values: Mapped[List["KPIValue"]] = relationship("KPIValue", back_populates="asset", cascade="all, delete-orphan")

    def __init__(self, **kwargs: Any) -> None:
        if "metadata_json" in kwargs:
            kwargs["metadata_"] = kwargs.pop("metadata_json")
        super().__init__(**kwargs)

    @property
    def metadata_json(self) -> dict:
        return self.metadata_

    @metadata_json.setter
    def metadata_json(self, value: dict) -> None:
        self.metadata_ = value

    __table_args__ = (
        CheckConstraint(
            "asset_type IN ('plant', 'block', 'inverter', 'string', 'transformer', 'meter', 'weather_station', 'turbine', 'sensor')",
            name="ck_assets_asset_type",
        ),
        UniqueConstraint(
            "plant_id",
            "name",
            name="uq_assets_plant_name",
        ),
    )


class CanonicalSignal(Base):
    """Canonical Telemetry Signal definition."""

    __tablename__ = "canonical_signals"

    key: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    unit: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    y_min: Mapped[Optional[float]] = mapped_column(
        Numeric,
        nullable=True,
    )
    y_max: Mapped[Optional[float]] = mapped_column(
        Numeric,
        nullable=True,
    )
    applicable_types: Mapped[List[str]] = mapped_column(
        JSON().with_variant(ARRAY(Text), "postgresql"),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    channels: Mapped[List["Channel"]] = relationship("Channel", back_populates="canonical_signal")

    def __init__(self, **kwargs: Any) -> None:
        if "signal_key" in kwargs:
            kwargs["key"] = kwargs.pop("signal_key")
        if "display_name" in kwargs:
            kwargs["name"] = kwargs.pop("display_name")
        kwargs.pop("data_type", None)
        kwargs.pop("monotonicity", None)
        kwargs.pop("bound_min_rule", None)
        kwargs.pop("bound_max_rule", None)
        kwargs.pop("is_active", None)
        if "applicable_types" not in kwargs:
            kwargs["applicable_types"] = ["inverter", "weather_station", "sensor"]
        super().__init__(**kwargs)

    @property
    def signal_key(self) -> str:
        return self.key

    @signal_key.setter
    def signal_key(self, value: str) -> None:
        self.key = value

    @property
    def display_name(self) -> str:
        return self.name

    @display_name.setter
    def display_name(self, value: str) -> None:
        self.name = value


class Channel(Base):
    """Configured ingestion channel."""

    __tablename__ = "channels"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    asset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("canonical_signals.key"),
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    receive_unit: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    conversion: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    interval_s: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    agg_semantics: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="avg",
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="channels")
    canonical_signal: Mapped["CanonicalSignal"] = relationship("CanonicalSignal", back_populates="channels")
    readings: Mapped[List["Reading"]] = relationship("Reading", back_populates="channel", cascade="all, delete-orphan")

    def __init__(self, **kwargs: Any) -> None:
        if "canonical_signal_key" in kwargs:
            kwargs["canonical_key"] = kwargs.pop("canonical_signal_key")
        if "source_unit" in kwargs:
            kwargs["receive_unit"] = kwargs.pop("source_unit")
        if "aggregation_method" in kwargs:
            kwargs["agg_semantics"] = kwargs.pop("aggregation_method")
        kwargs.pop("metadata_json", None)
        kwargs.pop("metadata", None)
        super().__init__(**kwargs)

    @property
    def canonical_signal_key(self) -> str:
        return self.canonical_key

    @canonical_signal_key.setter
    def canonical_signal_key(self, value: str) -> None:
        self.canonical_key = value

    @property
    def source_unit(self) -> Optional[str]:
        return self.receive_unit

    @source_unit.setter
    def source_unit(self, value: Optional[str]) -> None:
        self.receive_unit = value

    @property
    def aggregation_method(self) -> str:
        return self.agg_semantics

    @aggregation_method.setter
    def aggregation_method(self, value: str) -> None:
        self.agg_semantics = value

    @property
    def metadata_json(self) -> dict:
        return {}

    @metadata_json.setter
    def metadata_json(self, value: dict) -> None:
        pass

    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "canonical_key",
            "source_name",
            name="uq_channels_asset_canonical_source",
        ),
    )


class File(Base):
    """Uploaded or generated file."""

    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    original_name: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    size_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="files")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('raw_upload', 'report', 'export')",
            name="ck_files_kind",
        ),
    )


class MappingTemplate(Base):
    """Saved mapping template."""

    __tablename__ = "mapping_templates"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    source_signature: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    mappings: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="mapping_templates")

    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "source_signature",
            name="uq_mapping_templates_org_source_signature",
        ),
    )


class IngestionJob(Base):
    """File Ingestion Job."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mapping_templates.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="pending",
    )
    rows_total: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
    )
    time_min: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    time_max: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    qc_summary: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        server_default="{}",
    )
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    file: Mapped["File"] = relationship("File")
    template: Mapped["MappingTemplate"] = relationship("MappingTemplate")
    readings: Mapped[List["Reading"]] = relationship("Reading", back_populates="ingestion_job")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'profiling', 'awaiting_mapping', 'ingesting', 'qc', 'done', 'failed', 'processing', 'completed')",
            name="ck_ingestion_jobs_status",
        ),
    )


class Reading(Base):
    """Time-series reading."""

    __tablename__ = "readings"

    channel_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
    )
    value: Mapped[float] = mapped_column(
        Numeric,
        nullable=False,
    )
    quality: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    ingestion_job_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    channel: Mapped["Channel"] = relationship("Channel", back_populates="readings")
    ingestion_job: Mapped[Optional["IngestionJob"]] = relationship("IngestionJob", back_populates="readings")

    @property
    def timestamp(self) -> datetime:
        return self.ts

    @timestamp.setter
    def timestamp(self, value: datetime) -> None:
        self.ts = value

    @property
    def qc_flag(self) -> int:
        return self.quality

    @qc_flag.setter
    def qc_flag(self, value: int) -> None:
        self.quality = value


class JobHistory(Base):
    """Audit and run history for background jobs."""

    __tablename__ = "job_history"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), default="pipeline_benchmark", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    dataset_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dataset_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_observations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    throughput_rows_per_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qc_summary: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class KPIValue(Base):
    """Calculated KPI value record per plant and asset (TimescaleDB hypertable)."""

    __tablename__ = "kpi_values"
    __table_args__ = (
        CheckConstraint("period IN ('day', 'month')", name="ck_kpi_values_period"),
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
    )
    plant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("plants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    asset_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=True,
    )
    kpi_key: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )
    period: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )
    value: Mapped[Optional[float]] = mapped_column(
        DOUBLE_PRECISION,
        nullable=True,
    )
    coverage: Mapped[float] = mapped_column(
        Numeric,
        nullable=False,
        server_default="1.0",
        default=1.0,
    )
    flags: Mapped[List[str]] = mapped_column(
        FlagsArray,
        nullable=False,
        server_default="{}",
        default=list,
    )

    plant: Mapped["Plant"] = relationship("Plant", back_populates="kpi_values")
    asset: Mapped[Optional["Asset"]] = relationship("Asset", back_populates="kpi_values")