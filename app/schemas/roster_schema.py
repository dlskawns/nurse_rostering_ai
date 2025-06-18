from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class RosterRequest(BaseModel):
    request: str
    schema: List[Dict[str, Any]]

class RosterResponse(BaseModel):
    response: Any

class NurseProfile(BaseModel):
    nurse_id: str
    group_id: str
    account_id: str
    name: str
    experience: Optional[int] = None
    role: Optional[str] = None
    level: Optional[str] = None
    is_head_nurse: bool = Field(default=False)
    is_night_nurse: bool = Field(default=False)
    personal_off_adjustment: int = Field(default=0)
    preceptor_id: Optional[str] = None

    class Config:
        from_attributes = True