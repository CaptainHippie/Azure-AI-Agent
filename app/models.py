from pydantic import BaseModel
from typing import List, Optional

class AskRequest(BaseModel):
    query: str
    session_id: str = "default_session"
    # This allows the frontend to say "Only search inside policy.pdf"
    target_file: Optional[str] = None 

class AskResponse(BaseModel):
    answer: str
    source: List[str] = []