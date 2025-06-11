from pydantic import BaseModel
from models.database import DatabaseConfig

class QueryRequest(BaseModel):
    query: str
    config: DatabaseConfig 