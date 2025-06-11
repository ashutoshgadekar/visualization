from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from services.database import DatabaseService
from services.gemini import GeminiService
from models.query import QueryRequest
from models.database import DatabaseConfig

# Create router with proper prefix and tags
router = APIRouter(
    prefix="/query",
    tags=["query"],
    responses={
        200: {"description": "Successful response"},
        400: {"description": "Bad request"},
        500: {"description": "Internal server error"}
    }
)

gemini_service = GeminiService()

@router.post("", response_model=Dict[str, Any])
async def process_query(request: QueryRequest):
    try:
        # Initialize database service with configuration
        db_service = DatabaseService(request.config)
        
        try:
            # Get all tables
            tables = db_service.get_all_tables()
            
            # Get schema and sample data for each table
            tables_info = []
            for table_name in tables:
                try:
                    schema = db_service.get_table_schema(table_name)
                    sample = db_service.get_table_sample(table_name)
                    if sample:  # Only include tables that have data
                        tables_info.append({
                            'name': table_name,
                            'schema': schema,
                            'sample': sample[0] if sample else {}
                        })
                except Exception as e:
                    print(f"Warning: Could not get info for table {table_name}: {str(e)}")
                    continue
            
            if not tables_info:
                raise ValueError("No tables found with data in the database")
            
            # Generate SQL query
            sql_query = gemini_service.natural_language_to_sql(
                query=request.query,
                tables_info=tables_info
            )
            
            # Execute the query
            data = db_service.execute_query(sql_query)
            
            # Get the table name from the query for the response
            # This is a simple heuristic - in practice, you might want to parse the SQL
            table_name = "Query Results"
            if "FROM" in sql_query.upper():
                from_clause = sql_query.upper().split("FROM")[1].split()[0]
                table_name = from_clause.strip()
            
            # Generate dashboard response
            response = gemini_service.generate_dashboard_response(
                query=request.query,
                data=data,
                sql_query=sql_query,
                table_name=table_name
            )
            
            return response
        finally:
            # Always close the database connection
            db_service.close()
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 