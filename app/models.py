from sqlalchemy import Column, Integer, String, Text, Numeric

from app.database import Base


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    property_no = Column(String, unique=True, index=True)
    owner_name = Column(Text, nullable=False)
    address = Column(Text, nullable=False)
    annual_value = Column(Numeric, nullable=False)
    rate_due = Column(Numeric, nullable=False)
    year = Column(Integer, nullable=False)