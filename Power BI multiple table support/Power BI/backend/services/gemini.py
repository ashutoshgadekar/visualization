from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import sqlalchemy
import pandas as pd

from utils.db_utils import create_engine_from_config
from utils.analytics import extract_metrics_and_charts, extract_insights

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class DBConfig(BaseModel):
    driver: str
    server: str
    port: int
    database: str
    username: str
    password: str

class QueryRequest(BaseModel):
    config: DBConfig
    query: str

# Endpoints
@app.post("/api/test-connection")
def test_connection(config: DBConfig):
    try:
        engine = create_engine_from_config(config)
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/query")
def run_query(req: QueryRequest):
    try:
        engine = create_engine_from_config(req.config)
        df = pd.read_sql(req.query, engine)

        metrics, visualizations = extract_metrics_and_charts(df)
        insights = extract_insights(df)

        return {
            "metrics": metrics,
            "visualizations": visualizations,
            "insights": insights,
            "metadata": {
                "data_points": len(df),
                "columns": list(df.columns),
                "raw_data": df.to_dict(orient="records")
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
