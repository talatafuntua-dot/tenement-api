from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Numeric,
    DateTime
)
from sqlalchemy.sql import func

from app.database import Base


class Property(Base):
    __tablename__ = "properties"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # Unique LG / Property identifier
    property_no = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True
    )

    # Owner information
    owner_name = Column(
        Text,
        nullable=True,
        index=True
    )

    # Property address
    address = Column(
        Text,
        nullable=True
    )

    # Assessment information
    annual_value = Column(
        Numeric(15, 2),
        nullable=True
    )

    rate_due = Column(
        Numeric(15, 2),
        nullable=True
    )

    # Assessment year
    year = Column(
        Integer,
        nullable=True,
        index=True
    )

    # Optional status/payment information
    status = Column(
        String(50),
        nullable=True,
        index=True
    )

    # Record creation date
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # Last update date
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
