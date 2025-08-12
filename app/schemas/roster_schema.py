from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class ShiftManageSaveRequest(BaseModel):
    class_name: str
    slots: list  # [{"shift_slot": 1, "codes": ["D"], "manpower": 3}, ...]

class WantedDeadlineRequest(BaseModel):
    year: int
    month: int
    exp_date: Optional[datetime] = None

class MoveShiftRequest(BaseModel):
    shift_id: str
    new_sequence: int


class RemoveShiftRequest(BaseModel):
    shift_id: str

class ShiftAddRequest(BaseModel):
    shift_id: str
    name: str
    color: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    type: str  # Changed from 'type' to 'shift_type' to match frontend
    # time_type: str = "range"
    duration: Optional[int] = None
    allday: Optional[int] = 0
    auto_schedule: Optional[int] = 1

class RosterRequest(BaseModel):
    year: int
    month: int
    algorithm: str = "cp_sat"  # "cp_sat" or "random_sampling"
    config_id: Optional[int] = None

class PreferenceSubmit(BaseModel):
    year: int
    month: int

class PreferenceData(BaseModel):
    year: int
    month: int
    data: dict


class PublishRequest(BaseModel):
    schedule_id: str
    issue_comment: str = None

class WantedInvokeRequest(BaseModel):
    request: str| List[str]
    schema: List[Dict[str, Any]]
    case: object | None = None

class WantedInvokeResponse(BaseModel):
    response: Any

class RosterConfigBase(BaseModel):
    day_req: Optional[int] = 0
    eve_req: Optional[int] = 0
    nig_req: Optional[int] = 0
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
    even_nights: bool
    sequential_offs: bool

class RosterConfigCreate(RosterConfigBase):
    config_version: Optional[str] = None
    # pass

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