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

```
id = Column(Integer, primary_key=True, index=True)

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
```

class NoticeTemplate(Base):
_tablename_ = "notice_templates"

```
id = Column(
    Integer,
    primary_key=True,
    index=True
)

name = Column(
    String(200),
    unique=True,
    nullable=False
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

updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False
)
```
