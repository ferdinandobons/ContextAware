from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from enum import Enum

class ContextLayer(str, Enum):
    GLOBAL = "global"
    PROJECT = "project"
    SEMANTIC = "semantic"
    TASK = "task"
    WORKING = "working"
    DECISION = "decision"

class ContextItem(BaseModel):
    id: str
    layer: ContextLayer
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_file: Optional[str] = None
    line_number: Optional[int] = None
