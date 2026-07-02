from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import crud

router = APIRouter(
    prefix="/properties",
    tags=["Properties"]
)

@router.get("/")
def get_properties(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    return crud.get_all_properties(db, skip, limit)


@router.get("/search/owner")
def search_by_owner(
    owner_name: str,
    db: Session = Depends(get_db)
):
    return crud.search_owner(db, owner_name)


# This route accepts property numbers containing '/'
@router.get("/{property_no:path}")
def get_property(
    property_no: str,
    db: Session = Depends(get_db)
):
    property = crud.get_property_by_number(db, property_no)

    if not property:
        raise HTTPException(
            status_code=404,
            detail="Property not found"
        )

    return property