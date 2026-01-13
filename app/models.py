from pydantic import BaseModel
from typing import Optional, Dict, Any

class AskRequest(BaseModel):
    """
    Defines the payload expected from the frontend chat interface.
    """
    query: str
    session_id: str = "default_session"
    # This optional field carries the specific filename selected in the UI dropdown,
    # allowing the backend to restrict the search scope.
    target_file: Optional[str] = None 

class AskResponse(BaseModel):
    """
    Standardizes the response structure.
    """
    answer: str
    # We use a flexible dictionary here to support rich citations (URLs + Context)
    # Format: { "doc_name": { "url": "...", "context": [...] } }
    source: Dict[str, Any] = {}