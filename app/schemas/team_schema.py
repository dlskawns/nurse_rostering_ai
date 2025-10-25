from typing import List, Optional
from pydantic import BaseModel, Field


class TeamOps(BaseModel):
    """팀 단위 증분 오퍼레이션(생성/이름변경/멤버 추가/해제)."""
    team_id: Optional[int] = None
    team_name: Optional[str] = None
    add: List[str] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)


class TeamBulkOpsRequest(BaseModel):
    """팀 증분 동기화 요청 바디.
    - teams: 팀별 add/remove/rename/create
    - delete_team_ids: 팀 삭제(soft) 목록
    """
    teams: List[TeamOps] = Field(default_factory=list)
    delete_team_ids: List[int] = Field(default_factory=list)


class TeamWithMembers(BaseModel):
    """팀 + 멤버 목록 응답 DTO."""
    team_id: int
    team_name: str
    team_members: List[str]


