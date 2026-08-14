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

total_annual_value = (
    db.query(func.coalesce(func.sum(Property.annual_value), 0))
    .scalar()
)

total_rate_due = (
    db.query(func.coalesce(func.sum(Property.rate_due), 0))
    .scalar()
)

average_rate_due = (
    db.query(func.coalesce(func.avg(Property.rate_due), 0))
    .scalar()
)

return {
    "total_properties": total_properties,
    "total_annual_value": float(total_annual_value or 0),
    "total_rate_due": float(total_rate_due or 0),
    "average_rate_due": float(average_rate_due or 0)
}
```

@router.get("/by-year")
def report_by_year(db: Session = Depends(get_db)):

```
results = (
    db.query(
        Property.year,
        func.count(Property.id).label("property_count"),
        func.sum(Property.annual_value).label("annual_value"),
        func.sum(Property.rate_due).label("rate_due")
    )
    .group_by(Property.year)
    .order_by(Property.year)
    .all()
)

return [
    {
        "year": row.year,
        "property_count": row.property_count,
        "annual_value": float(row.annual_value or 0),
        "rate_due": float(row.rate_due or 0)
    }
    for row in results
]
```

@router.get("/by-rating-area")
def report_by_rating_area(db: Session = Depends(get_db)):

```
results = (
    db.query(
        Property.rating_area,
        func.count(Property.id).label("property_count"),
        func.sum(Property.annual_value).label("annual_value"),
        func.sum(Property.rate_due).label("rate_due")
    )
    .group_by(Property.rating_area)
    .order_by(Property.rating_area)
    .all()
)

return [
    {
        "rating_area": row.rating_area,
        "property_count": row.property_count,
        "annual_value": float(row.annual_value or 0),
        "rate_due": float(row.rate_due or 0)
    }
    for row in results
]
```

@router.get("/by-status")
def report_by_status(db: Session = Depends(get_db)):

```
results = (
    db.query(
        Property.status,
        func.count(Property.id).label("property_count"),
        func.sum(Property.rate_due).label("rate_due")
    )
    .group_by(Property.status)
    .order_by(Property.status)
    .all()
)

return [
    {
        "status": row.status,
        "property_count": row.property_count,
        "rate_due": float(row.rate_due or 0)
    }
    for row in results
]
```
