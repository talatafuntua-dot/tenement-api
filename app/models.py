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

    id = Column(Integer, primary_key=True, index=True)

    # Unique Property Number
    property_no = Column(String(50), unique=True, nullable=False, index=True)

    # Owner Information
    owner_name = Column(Text, nullable=False)

    # Property Address
    address = Column(Text, nullable=False)

    # Rating Area / Ward / Zone
    rating_area = Column(String(100), nullable=True)

    # Financial Information
    annual_value = Column(Numeric(18, 2), nullable=False)

    rate_due = Column(Numeric(18, 2), nullable=False)

    # Assessment Year
    year = Column(Integer, nullable=False)

    # Payment Status
    status = Column(String(20), default="UNPAID", nullable=False)

    # Audit Information
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