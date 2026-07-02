from pydantic import BaseModel


class PropertyBase(BaseModel):
    property_no: str
    owner_name: str
    address: str
    annual_value: float
    rate_due: float
    year: int


class Property(PropertyBase):
    id: int

    class Config:
        from_attributes = True