from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class RosterRequest(BaseModel):
    request: str
    schema: List[Dict[str, Any]]

class RosterResponse(BaseModel):
    response: Any

class RosterConfigBase(BaseModel):
    day_req: int
    eve_req: int
    nig_req: int
    min_exp_per_shift: int
    req_exp_nurses: int
    two_offs_per_week: bool
    max_nig_per_month: int
    three_seq_nig: bool
    two_offs_after_three_nig: bool
    two_offs_after_two_nig: bool
    banned_day_after_eve: bool
    max_conseq_work: int
    off_days: int
    shift_priority: float
    weekend_shift_ratio: float
    patient_amount: int

class RosterConfigCreate(RosterConfigBase):
    pass

class RosterConfig(RosterConfigBase):
    config_id: int
    office_id: str
    group_id: str
    created_at: str

    class Config:
        from_attributes = True

class NurseProfile(BaseModel):
    nurse_id: str
    group_id: str
    account_id: str
    name: str
    experience: Optional[int] = None
    role: Optional[str] = None
    level_: Optional[str] = None
    is_head_nurse: bool = Field(default=False)
    is_night_nurse: bool = Field(default=False)
    personal_off_adjustment: int = Field(default=0)
    preceptor_id: Optional[str] = None
    joining_date: Optional[datetime] = None
    resignation_date: Optional[datetime] = None

    class Config:
        from_attributes = True