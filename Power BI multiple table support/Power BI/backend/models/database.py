from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class DatabaseConfig(BaseModel):
    server: str
    database: str
    username: str
    password: str
    port: Optional[int] = 1433  # Default SQL Server port
    db_type: str  # 'mysql' or 'postgresql'

class ChartSuggestion(BaseModel):
    chart_type: str
    title: str
    description: str

class QueryResponse(BaseModel):
    data: List[Dict[str, Any]]
    chart_suggestions: List[ChartSuggestion]
    sql_query: str 