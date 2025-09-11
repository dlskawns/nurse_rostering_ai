from pydantic import BaseModel
from typing import Optional

class TokenData(BaseModel):
    account_id: Optional[str] = None

class User(BaseModel):
    nurse_id: str
    account_id: str
    office_id: Optional[str] = None
    group_id: str
    is_head_nurse: bool
    name: str

    class Config:
        from_attributes = True  