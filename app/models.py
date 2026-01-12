from pydantic import BaseModel
from typing import Optional, Dict, Any

class AskRequest(BaseModel):
    query: str
    session_id: str = "default_session"
    target_file: Optional[str] = None 

class AskResponse(BaseModel):
    answer: str
    source: Dict[str, Any] = {}