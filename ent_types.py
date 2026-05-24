from pydantic import BaseModel, Field
from typing import Optional, List

class Entity(BaseModel):
    id: str = Field(description="Unique entity identitifier.")
    text: str = Field(description="The extract text of the named entity extracted from the documents.")
    type: str = Field(description="Entity type")
    normalized_value: Optional[str] = None
    confidence: Optional[float] = None

class Relationship(BaseModel):
    source: str = Field(description="Source entity ID")
    target: str = Field(description="Target entity ID")
    relation: str = Field(description="Relationship type")

class ExtractionResult(BaseModel):
    entities: List[Entity]
    relationships: List[Relationship]