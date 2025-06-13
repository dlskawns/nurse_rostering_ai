from pydantic import BaseModel
from typing import List, Dict, Any

class RosterRequest(BaseModel):
    request: str
    schema: List[Dict[str, Any]]

class RosterResponse(BaseModel):
    response: list