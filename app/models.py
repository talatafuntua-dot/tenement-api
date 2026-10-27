from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Numeric,
    DateTime,
    ForeignKey,
    UniqueConstraint
)

from sqlalchemy.sql import func

from app.database import Base


class LocalGovernment(Base):
    __tablename__ = "local_governments"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    name = Column(
        String(100),
        unique=True,
        nullable=False
    )

    code = Column(
        String(20),
        nullable=True
    )

    prefix = Column(
        String(10),
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )


class Property(Base):
    __tablename__ = "properties"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    property_no = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True
    )

    owner_name = Column(
        Text,
        nullable=False
    )

    address = Column(
        Text,
        nullable=False
    )

    rating_area = Column(
        String(100),
        nullable=True
    )

    annual_value = Column(
        Numeric(18, 2),
        nullable=False
    )

    rate_due = Column(
        Numeric(18, 2),
        nullable=False
    )

    year = Column(
        Integer,
        nullable=False
    )

    status = Column(
        String(20),
        default="UNPAID",
        nullable=False
    )

    lg_code = Column(
        String(50),
        unique=True,
        nullable=True,
        index=True
    )

    lg_id = Column(
        Integer,
        ForeignKey("local_governments.id"),
        nullable=True,
        index=True
    )

    lg_prefix = Column(
        String(10),
        nullable=True,
        index=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )


class NoticeTemplate(Base):
    __tablename__ = "notice_templates"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    name = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )

    filename = Column(
        String(255),
        nullable=False
    )

    file_path = Column(
        Text,
        nullable=False
    )

    description = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

# ADD THESE IMPORTS to app/models.py (keep all existing imports/classes):
from sqlalchemy import UniqueConstraint

# ADD THESE TWO CLASSES AFTER your existing NoticeTemplate class.
# They use the existing Base and Property models.

class JournalField(Base):
    __tablename__ = "journal_fields"

    id = Column(Integer, primary_key=True, index=True)
    field_key = Column(String(180), unique=True, nullable=False, index=True)
    label = Column(String(255), nullable=False, index=True)
    normalized_label = Column(String(180), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)
    occurrence = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class JournalValue(Base):
    __tablename__ = "journal_values"
    __table_args__ = (
        UniqueConstraint("property_id", "field_id", name="uq_journal_property_field"),
    )

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    field_id = Column(Integer, ForeignKey("journal_fields.id", ondelete="CASCADE"), nullable=False, index=True)
    value_text = Column(Text, nullable=True)
    value_numeric = Column(Numeric(18, 4), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

class LGCodeRegistry(Base):
    __tablename__ = "lg_code_registry"

    __table_args__ = (
        UniqueConstraint(
            "property_key",
            name="uq_lg_code_registry_property_key",
        ),
        UniqueConstraint(
            "lg_code",
            name="uq_lg_code_registry_lg_code",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    property_key = Column(
        String(255),
        nullable=False,
        index=True,
    )

    property_identifier = Column(
        String(255),
        nullable=False,
    )

    prefix_used = Column(
        String(50),
        nullable=True,
    )

    lg_code = Column(
        String(50),
        nullable=False,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
