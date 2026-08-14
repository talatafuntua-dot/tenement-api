from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Property

router = APIRouter(
prefix="/reports",
tags=["Reports"]
)

@router.get("/summary")
def report_summary(db: Session = Depends(get_db)):

```
total_properties = db.query(Property).count()

total_annual_value = db.query(
    func.coalesce(
        func.sum(Property.annual_value),
        0
    )
).scalar()

total_rate_due = db.query(
    func.coalesce(
        func.sum(Property.rate_due),
        0
    )
).scalar()

average_rate_due = db.query(
    func.coalesce(
        func.avg(Property.rate_due),
        0
    )
).scalar()

return {
    "total_properties": total_properties,
    "total_annual_value": float(total_annual_value or 0),
    "total_rate_due": float(total_rate_due or 0),
    "average_rate_due": float(average_rate_due or 0)
}
```
