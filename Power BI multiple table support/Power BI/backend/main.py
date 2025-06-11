import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import sqlalchemy as sa
from sqlalchemy import create_engine, text
import pandas as pd
import json
import google.generativeai as genai
from datetime import datetime
import traceback
import sys
import mysql.connector
from mysql.connector import Error
import logging
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# Initialize FastAPI app
app = FastAPI(
    title="Natural Language Query API",
    description="API for converting natural language queries to SQL and generating dashboard visualizations",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Gemini
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

class DatabaseConfig(BaseModel):
    driver: str
    server: str
    port: int
    database: str
    username: str
    password: str

class QueryRequest(BaseModel):
    config: DatabaseConfig
    query: str

def get_db_connection(config: DatabaseConfig):
    try:
        logger.info(f"Attempting to connect to database: {config.database} on {config.server}:{config.port}")
        connection = mysql.connector.connect(
            host=config.server,
            port=config.port,
            database=config.database,
            user=config.username,
            password=config.password
        )
        logger.info("Database connection successful")
        return connection
    except Error as e:
        error_msg = f"Database connection error: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

def get_foreign_key_relationships(connection) -> Dict[str, List[Dict[str, str]]]:
    """
    Get foreign key relationships between tables
    """
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Query to get foreign key constraints
        fk_query = """
        SELECT 
            kcu.TABLE_NAME as source_table,
            kcu.COLUMN_NAME as source_column,
            kcu.REFERENCED_TABLE_NAME as target_table,
            kcu.REFERENCED_COLUMN_NAME as target_column,
            kcu.CONSTRAINT_NAME as constraint_name
        FROM 
            INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
        WHERE 
            kcu.TABLE_SCHEMA = %s 
            AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY 
            kcu.TABLE_NAME, kcu.COLUMN_NAME
        """
        
        cursor.execute(fk_query, (connection.database,))
        fk_results = cursor.fetchall()
        
        relationships = {}
        for fk in fk_results:
            source_table = fk['source_table']
            if source_table not in relationships:
                relationships[source_table] = []
            
            relationships[source_table].append({
                'source_column': fk['source_column'],
                'target_table': fk['target_table'],
                'target_column': fk['target_column'],
                'constraint_name': fk['constraint_name']
            })
        
        logger.info(f"Found {len(relationships)} tables with foreign key relationships")
        return relationships
        
    except Error as e:
        logger.warning(f"Could not retrieve foreign key relationships: {str(e)}")
        return {}

def detect_potential_relationships(connection, schema: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """
    Detect potential relationships based on column naming conventions and data patterns
    """
    try:
        potential_relationships = {}
        table_names = list(schema.keys())
        
        # Common patterns for foreign key naming conventions
        fk_patterns = [
            r'(.+)_id$',           # table_id
            r'id_(.+)$',           # id_table
            r'(.+)id$',            # tableid
            r'fk_(.+)$',           # fk_table
            r'(.+)_key$',          # table_key
        ]
        
        for table_name, table_info in schema.items():
            columns = table_info['columns']
            potential_relationships[table_name] = []
            
            for column in columns:
                col_name = column['Field'].lower()
                
                # Skip primary keys of the same table
                if column['Key'] == 'PRI' and col_name in [f"{table_name}_id", "id"]:
                    continue
                
                # Check against naming patterns
                for pattern in fk_patterns:
                    match = re.match(pattern, col_name)
                    if match:
                        referenced_table = match.group(1)
                        
                        # Look for matching table names (exact or partial match)
                        for target_table in table_names:
                            if target_table != table_name:
                                # Check for exact match or partial match
                                if (referenced_table == target_table.lower() or 
                                    referenced_table in target_table.lower() or 
                                    target_table.lower() in referenced_table):
                                    
                                    # Try to find the primary key column in target table
                                    target_pk = None
                                    for target_col in schema[target_table]['columns']:
                                        if target_col['Key'] == 'PRI':
                                            target_pk = target_col['Field']
                                            break
                                    
                                    if not target_pk:
                                        target_pk = 'id'  # Default assumption
                                    
                                    potential_relationships[table_name].append({
                                        'source_column': column['Field'],
                                        'target_table': target_table,
                                        'target_column': target_pk,
                                        'confidence': 'high' if referenced_table == target_table.lower() else 'medium',
                                        'type': 'inferred'
                                    })
        
        # Filter out empty relationships
        potential_relationships = {k: v for k, v in potential_relationships.items() if v}
        
        logger.info(f"Detected {len(potential_relationships)} potential relationships")
        return potential_relationships
        
    except Exception as e:
        logger.warning(f"Error detecting potential relationships: {str(e)}")
        return {}

def get_table_relationships(connection, schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get both explicit foreign key relationships and inferred relationships
    """
    try:
        # Get explicit foreign key relationships
        fk_relationships = get_foreign_key_relationships(connection)
        
        # Get potential relationships based on naming conventions
        potential_relationships = detect_potential_relationships(connection, schema)
        
        # Combine relationships
        all_relationships = {}
        
        # Add explicit relationships
        for table, relationships in fk_relationships.items():
            if table not in all_relationships:
                all_relationships[table] = []
            for rel in relationships:
                rel['type'] = 'foreign_key'
                all_relationships[table].append(rel)
        
        # Add potential relationships (avoid duplicates)
        for table, relationships in potential_relationships.items():
            if table not in all_relationships:
                all_relationships[table] = []
            
            existing_pairs = set()
            for existing_rel in all_relationships[table]:
                existing_pairs.add((existing_rel['source_column'], existing_rel['target_table']))
            
            for rel in relationships:
                pair = (rel['source_column'], rel['target_table'])
                if pair not in existing_pairs:
                    all_relationships[table].append(rel)
        
        logger.info(f"Total relationships found: {sum(len(rels) for rels in all_relationships.values())}")
        return all_relationships
        
    except Exception as e:
        logger.error(f"Error getting table relationships: {str(e)}")
        return {}

def format_relationships_for_prompt(relationships: Dict[str, Any]) -> str:
    """
    Format relationships in a readable way for the AI prompt
    """
    if not relationships:
        return "No table relationships detected."
    
    relationship_text = "\nTABLE RELATIONSHIPS:\n"
    relationship_text += "="*50 + "\n"
    
    for source_table, rels in relationships.items():
        if rels:
            relationship_text += f"\nTable: {source_table}\n"
            for rel in rels:
                rel_type = rel.get('type', 'unknown')
                confidence = rel.get('confidence', 'confirmed')
                
                if rel_type == 'foreign_key':
                    status = "[CONFIRMED FK]"
                elif confidence == 'high':
                    status = "[HIGH CONFIDENCE]"
                elif confidence == 'medium':
                    status = "[MEDIUM CONFIDENCE]"
                else:
                    status = "[INFERRED]"
                
                relationship_text += f"  - {rel['source_column']} → {rel['target_table']}.{rel['target_column']} {status}\n"
    
    relationship_text += "\nJOIN PATTERNS:\n"
    relationship_text += "-" * 30 + "\n"
    
    # Generate common JOIN patterns
    for source_table, rels in relationships.items():
        for rel in rels:
            join_pattern = f"JOIN {rel['target_table']} ON {source_table}.{rel['source_column']} = {rel['target_table']}.{rel['target_column']}"
            relationship_text += f"  {join_pattern}\n"
    
    return relationship_text

def get_table_schema(connection) -> Dict[str, Any]:
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        
        schema = {}
        for table in tables:
            table_name = list(table.values())[0]
            cursor.execute(f"DESCRIBE {table_name}")
            columns = cursor.fetchall()
            schema[table_name] = {
                'columns': columns,
                'sample_data': []
            }
        
        logger.info(f"Retrieved schema for {len(schema)} tables")
        return schema
    except Error as e:
        error_msg = f"Error getting database schema: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

def get_sample_data(connection, schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get sample data (first few rows) from each table to help with query generation
    """
    try:
        cursor = connection.cursor(dictionary=True)
        
        for table_name in schema.keys():
            try:
                # Get first 3 rows of sample data
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                sample_rows = cursor.fetchall()
                schema[table_name]['sample_data'] = sample_rows
                logger.info(f"Retrieved {len(sample_rows)} sample rows from {table_name}")
            except Error as e:
                logger.warning(f"Could not get sample data from {table_name}: {str(e)}")
                schema[table_name]['sample_data'] = []
        
        return schema
    except Error as e:
        error_msg = f"Error getting sample data: {str(e)}"
        logger.error(error_msg)
        # Don't fail the entire process if sample data fails
        return schema

def determine_if_chart_needed(natural_query: str) -> bool:
    """
    Determine if the user query requires a chart/visualization
    """
    chart_keywords = [
        'chart', 'graph', 'plot', 'visualization', 'visualize', 'show', 'display',
        'trend', 'distribution', 'comparison', 'compare', 'analyze', 'analysis',
        'breakdown', 'summary', 'overview', 'dashboard', 'report', 'statistics',
        'stats', 'percentage', 'ratio', 'top', 'bottom', 'highest', 'lowest',
        'average', 'total', 'sum', 'count', 'group by', 'order by'
    ]
    
    # Convert query to lowercase for case-insensitive matching
    query_lower = natural_query.lower()
    
    # Check for chart-related keywords
    for keyword in chart_keywords:
        if keyword in query_lower:
            return True
    
    # Check for aggregation patterns that typically need visualization
    aggregation_patterns = [
        r'\b(count|sum|avg|average|max|min|total)\b',
        r'\bgroup\s+by\b',
        r'\border\s+by\b',
        r'\btop\s+\d+\b',
        r'\bbottom\s+\d+\b'
    ]
    
    for pattern in aggregation_patterns:
        if re.search(pattern, query_lower):
            return True
    
    # Check for "how many" questions which typically need visualization
    how_many_patterns = [
        r'\bhow\s+many\b',
        r'\bhow\s+much\b',
        r'\bwhat\s+is\s+the\s+(count|number|total)\b',
        r'\bcount\s+of\b',
        r'\bnumber\s+of\b'
    ]
    
    for pattern in how_many_patterns:
        if re.search(pattern, query_lower):
            return True
    
    # Check for grouping/categorization questions
    grouping_patterns = [
        r'\bper\s+\w+\b',  # "per section", "per department", etc.
        r'\bby\s+\w+\b',   # "by category", "by region", etc.
        r'\beach\s+\w+\b', # "each department", "each class", etc.
        r'\bevery\s+\w+\b' # "every category", etc.
    ]
    
    for pattern in grouping_patterns:
        if re.search(pattern, query_lower):
            return True
    
    # Check for comparative questions
    comparative_patterns = [
        r'\bwhich\s+\w+\s+(has|have)\s+(more|most|less|least)\b',
        r'\bcompare\b',
        r'\bdifference\s+between\b'
    ]
    
    for pattern in comparative_patterns:
        if re.search(pattern, query_lower):
            return True
    
    return False

def generate_sql_query(natural_query: str, schema: Dict[str, Any], relationships: Dict[str, Any]) -> str:
    try:
        # Format schema information with sample data for better understanding
        schema_info = []
        for table_name, table_info in schema.items():
            columns = table_info['columns']
            sample_data = table_info.get('sample_data', [])
            
            column_info = []
            for col in columns:
                col_name = col['Field']
                col_type = col['Type']
                col_key = col['Key']
                is_nullable = col['Null'] == 'YES'
                default_val = col['Default']
                
                col_desc = f"{col_name} ({col_type})"
                if col_key == 'PRI':
                    col_desc += " [PRIMARY KEY]"
                elif col_key == 'UNI':
                    col_desc += " [UNIQUE]"
                elif col_key == 'MUL':
                    col_desc += " [INDEX]"
                
                if not is_nullable:
                    col_desc += " [NOT NULL]"
                    
                column_info.append(col_desc)
            
            table_desc = f"Table: {table_name}\nColumns: {', '.join(column_info)}"
            
            # Add sample data if available
            if sample_data:
                table_desc += f"\n\nSample Data from {table_name}:"
                for i, row in enumerate(sample_data, 1):
                    row_data = ", ".join([f"{k}: {v}" for k, v in row.items()])
                    table_desc += f"\nRow {i}: {row_data}"
            
            schema_info.append(table_desc)
        
        schema_text = "\n\n" + "="*50 + "\n\n".join(schema_info)
        
        # Format relationships for the prompt
        relationships_text = format_relationships_for_prompt(relationships)

        # Enhanced system prompt with relationship awareness
        system_prompt = """You are an expert SQL query generator with deep knowledge of MySQL syntax, database design patterns, and relational database concepts. Your role is to convert natural language questions into precise, efficient SQL queries that properly utilize table relationships.

CORE RESPONSIBILITIES:
1. Generate ONLY valid MySQL SELECT statements
2. Ensure queries are syntactically correct and executable
3. Use appropriate JOINs based on table relationships provided
4. Utilize WHERE clauses, aggregations, and sorting effectively
5. Follow MySQL best practices and conventions
6. Handle edge cases and potential data issues
7. Analyze sample data to understand data patterns and relationships
8. Leverage foreign key relationships and inferred relationships for accurate JOINs

RELATIONSHIP HANDLING:
- ALWAYS use the provided table relationships when queries involve multiple tables
- Prefer CONFIRMED FK relationships over inferred ones
- Use appropriate JOIN types (INNER, LEFT, RIGHT) based on query requirements
- Consider the direction of relationships when writing JOINs
- Use table aliases consistently (t1, t2, etc.) for readability

QUERY REQUIREMENTS:
- Start with SELECT keyword
- Use proper table aliases (t1, t2, etc.)
- Include appropriate WHERE conditions for filtering
- Use GROUP BY for aggregated data
- Add ORDER BY for sorting when logical
- Use LIMIT when appropriate for performance
- Handle NULL values appropriately
- Use proper date/time functions for temporal data
- Pay attention to sample data to understand actual data structure and values

MULTI-TABLE QUERY GUIDELINES:
- When a query involves data from multiple tables, ALWAYS check the relationships section
- Use the exact JOIN patterns provided in the relationships section
- Maintain referential integrity in your queries
- Consider the business logic implied by the relationships

DATA ANALYSIS GUIDELINES:
- Look at sample data to understand actual column values and patterns
- Identify relationships between tables based on both explicit FKs and sample data
- Use appropriate filtering conditions based on actual data values
- Consider data types and formats when writing conditions

COMMON PATTERNS TO RECOGNIZE:
- Fee payment queries: Look for fee_status, payment_status, is_paid, fee_paid columns
- Student information: Look for student_id, student_name, registration columns
- Status fields: Often contain values like 'paid'/'unpaid', 'active'/'inactive', 1/0, TRUE/FALSE
- Date fields: Consider current date comparisons for active records

RESPONSE FORMAT:
- Return ONLY the SQL query
- No explanations, markdown, or additional text
- End with semicolon
- Use clean, readable formatting with proper indentation
- Use meaningful table aliases

EXAMPLES OF GOOD MULTI-TABLE QUERIES:
- SELECT t1.name, t2.course_name FROM students t1 JOIN courses t2 ON t1.course_id = t2.id;
- SELECT t1.student_name, SUM(t2.amount) as total_fees FROM students t1 JOIN fees t2 ON t1.id = t2.student_id GROUP BY t1.id;
- SELECT t1.*, t2.department_name FROM employees t1 LEFT JOIN departments t2 ON t1.dept_id = t2.id WHERE t1.status = 'active';"""

        # Create the user query prompt with schema, sample data, and relationships
        user_prompt = f"""
Database Schema with Sample Data:
{schema_text}

{relationships_text}

Natural Language Query: {natural_query}

IMPORTANT: 
1. Analyze the sample data carefully to understand actual data structure and values
2. Use the table relationships provided above for any multi-table queries
3. Follow the exact JOIN patterns when connecting tables
4. Consider both confirmed foreign keys and high-confidence inferred relationships
5. Use appropriate table aliases for readability

Generate a MySQL query that answers this question accurately and efficiently based on the actual data structure and relationships shown above.
"""

        logger.info("Generating SQL query using Gemini with enhanced prompt, sample data, and relationships")
        
        # Generate content with system instruction
        response = model.generate_content(
            [{"text": system_prompt}, {"text": user_prompt}]
        )
        
        sql_query = response.text.strip()
        
        # Clean up the response more thoroughly
        sql_query = sql_query.replace('```sql', '').replace('```', '').strip()
        
        # Remove any extra explanatory text
        lines = sql_query.split('\n')
        sql_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('--') and not line.startswith('#'):
                sql_lines.append(line)
        
        sql_query = ' '.join(sql_lines)
        
        # Ensure query ends with semicolon
        if not sql_query.endswith(';'):
            sql_query += ';'
        
        # Validate that the response is a SQL query
        if not sql_query.lower().startswith('select'):
            error_msg = f"Generated response is not a valid SQL query. Got: {sql_query}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Generated SQL query: {sql_query}")
        return sql_query
    except Exception as e:
        error_msg = f"Error generating SQL query: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

def execute_query(connection, query: str) -> List[Dict[str, Any]]:
    try:
        cursor = connection.cursor(dictionary=True)
        logger.info(f"Executing query: {query}")
        cursor.execute(query)
        results = cursor.fetchall()
        logger.info(f"Query executed successfully. Retrieved {len(results)} rows")
        return results
    except Error as e:
        error_msg = f"Error executing query: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

def is_data_suitable_for_visualization(data: List[Dict[str, Any]]) -> bool:
    """
    Check if the data is suitable for visualization based on structure and content
    """
    if not data or len(data) == 0:
        return False
    
    # Check if we have reasonable amount of data (not too little, not too much for charts)
    if len(data) < 2:
        return False
    
    if len(data) > 1000:  # Too much data might not be suitable for simple charts
        return False
    
    columns = list(data[0].keys())
    
    # Check if we have at least one numeric or categorical column suitable for visualization
    numeric_columns = [col for col in columns if isinstance(data[0][col], (int, float))]
    categorical_columns = [col for col in columns if not isinstance(data[0][col], (int, float))]
    
    # Need at least one column for meaningful visualization
    if len(numeric_columns) == 0 and len(categorical_columns) == 0:
        return False
    
    return True

def generate_visualizations(data: List[Dict[str, Any]], needs_chart: bool) -> List[Dict[str, Any]]:
    """
    Generate visualizations only if charts are needed and data is suitable
    """
    if not needs_chart or not data or not is_data_suitable_for_visualization(data):
        return []

    visualizations = []
    columns = list(data[0].keys())
    
    # Identify categorical and numeric columns
    numeric_columns = [col for col in columns if isinstance(data[0][col], (int, float))]
    categorical_columns = [col for col in columns if not isinstance(data[0][col], (int, float))]
    
    # Strategy 1: If we have both categorical and numeric columns, create meaningful combinations
    if categorical_columns and numeric_columns:
        # Create bar chart with categorical labels and numeric values
        cat_col = categorical_columns[0]  # Primary categorical column
        num_col = numeric_columns[0]      # Primary numeric column
        
        # Extract labels and values maintaining order
        labels = []
        values = []
        for row in data:
            if row[cat_col] is not None and row[num_col] is not None:
                labels.append(str(row[cat_col]))
                values.append(row[num_col])
        
        if labels and values:
            visualizations.append({
                "type": "bar",
                "title": f"{num_col.replace('_', ' ').title()} by {cat_col.replace('_', ' ').title()}",
                "data": {
                    "labels": labels,
                    "values": values
                }
            })
            
            # Also create pie chart if suitable (not too many categories)
            if len(labels) <= 10:
                visualizations.append({
                    "type": "pie",
                    "title": f"{num_col.replace('_', ' ').title()} Distribution by {cat_col.replace('_', ' ').title()}",
                    "data": {
                        "labels": labels,
                        "values": values
                    }
                })
    
    # Strategy 2: Handle pure numeric data (create charts with row indices or calculated labels)
    elif numeric_columns and not categorical_columns:
        for col in numeric_columns[:2]:  # Limit to 2 numeric columns
            values = [row[col] for row in data if row[col] is not None]
            if len(values) > 0:
                # Use row indices as labels for pure numeric data
                labels = [f"Row {i+1}" for i in range(len(values))]
                visualizations.append({
                    "type": "bar",
                    "title": f"{col.replace('_', ' ').title()} Distribution",
                    "data": {
                        "labels": labels,
                        "values": values
                    }
                })
    
    # Strategy 3: Handle pure categorical data (count frequencies)
    elif categorical_columns and not numeric_columns:
        for col in categorical_columns[:1]:  # Limit to 1 categorical column
            value_counts = {}
            for row in data:
                if row[col] is not None:
                    value = str(row[col])
                    value_counts[value] = value_counts.get(value, 0) + 1
            
            if len(value_counts) > 1 and len(value_counts) <= 10:
                visualizations.append({
                    "type": "pie",
                    "title": f"{col.replace('_', ' ').title()} Distribution",
                    "data": {
                        "labels": list(value_counts.keys()),
                        "values": list(value_counts.values())
                    }
                })
                
                # Also add bar chart for categorical frequency
                visualizations.append({
                    "type": "bar",
                    "title": f"{col.replace('_', ' ').title()} Count",
                    "data": {
                        "labels": list(value_counts.keys()),
                        "values": list(value_counts.values())
                    }
                })

    return visualizations

def generate_metrics(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not data:
        return []

    metrics = []
    columns = list(data[0].keys())
    
    # Add count metric
    metrics.append({
        "title": "Total Records",
        "value": len(data),
        "type": "count"
    })

    # Add metrics for numeric columns
    numeric_columns = [col for col in columns if isinstance(data[0][col], (int, float))]
    for col in numeric_columns[:3]:  # Limit to 3 numeric columns
        values = [row[col] for row in data if row[col] is not None]
        if values:
            metrics.extend([
                {
                    "title": f"Average {col.replace('_', ' ').title()}",
                    "value": round(sum(values) / len(values), 2),
                    "type": "average"
                },
                {
                    "title": f"Max {col.replace('_', ' ').title()}",
                    "value": max(values),
                    "type": "maximum"
                },
                {
                    "title": f"Min {col.replace('_', ' ').title()}",
                    "value": min(values),
                    "type": "minimum"
                }
            ])

    return metrics

def generate_insights(data: List[Dict[str, Any]]) -> List[str]:
    if not data:
        return ["No data available to generate insights."]

    insights = []
    columns = list(data[0].keys())
    
    # Basic data insights
    insights.append(f"Dataset contains {len(data)} records with {len(columns)} columns.")
    
    # Generate insights for numeric columns
    numeric_columns = [col for col in columns if isinstance(data[0][col], (int, float))]
    for col in numeric_columns[:2]:  # Limit insights
        values = [row[col] for row in data if row[col] is not None]
        if values:
            avg = sum(values) / len(values)
            max_val = max(values)
            min_val = min(values)
            insights.append(f"The {col.replace('_', ' ')} ranges from {min_val} to {max_val}, with an average of {avg:.2f}.")

    # Generate insights for categorical columns
    categorical_columns = [col for col in columns if not isinstance(data[0][col], (int, float))]
    for col in categorical_columns[:2]:  # Limit insights
        value_counts = {}
        for row in data:
            if row[col] is not None:
                value = str(row[col])
                value_counts[value] = value_counts.get(value, 0) + 1
        
        if value_counts:
            most_common = max(value_counts.items(), key=lambda x: x[1])
            unique_count = len(value_counts)
            insights.append(f"The {col.replace('_', ' ')} has {unique_count} unique values. Most common value is '{most_common[0]}' appearing {most_common[1]} times.")

    return insights

@app.post("/api/query")
async def process_query(request: QueryRequest):
    connection = None
    try:
        logger.info(f"Processing query: {request.query}")
        logger.info(f"Database config: {request.config.dict()}")
        
        # Determine if chart is needed based on user query
        needs_chart = determine_if_chart_needed(request.query)
        logger.info(f"Chart needed: {needs_chart}")
        
        # Connect to database
        connection = get_db_connection(request.config)
        
        # Get database schema
        schema = get_table_schema(connection)
        
        # Get sample data for better query generation
        schema_with_samples = get_sample_data(connection, schema)
        
        # Get table relationships (both explicit FKs and inferred)
        relationships = get_table_relationships(connection, schema_with_samples)
        logger.info(f"Found relationships for {len(relationships)} tables")
        
        # Generate SQL query with enhanced prompt, sample data, and relationships
        sql_query = generate_sql_query(request.query, schema_with_samples, relationships)
        
        # Execute query
        results = execute_query(connection, sql_query)
        
        # Generate visualizations only if needed
        visualizations = generate_visualizations(results, needs_chart)
        
        # Generate metrics
        metrics = generate_metrics(results)
        
        # Generate insights
        insights = generate_insights(results)
        
        # Determine if graph was actually generated
        graph_generated = len(visualizations) > 0
        
        return {
            "metadata": {
                "raw_data": results,
                "data_points": len(results),
                "generated_sql": sql_query,
                "chart_requested": needs_chart,
                "data_suitable_for_viz": is_data_suitable_for_visualization(results) if results else False,
                "relationships_found": len(relationships),
                "tables_with_relationships": list(relationships.keys()) if relationships else []
            },
            "visualizations": visualizations,
            "metrics": metrics,
            "insights": insights,
            "graph_generated": graph_generated,
            "relationships": relationships  # Include relationships in response for debugging
        }
        
    except HTTPException as he:
        logger.error(f"HTTP Exception: {he.detail}")
        return JSONResponse(
            status_code=he.status_code,
            content={
                "detail": he.detail,
                "graph_generated": False
            }
        )
    except Exception as e:
        error_msg = f"Error processing query: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(e),
                "graph_generated": False
            }
        )
    finally:
        if connection:
            try:
                connection.close()
                logger.info("Database connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {str(e)}")

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "gemini_configured": bool(GEMINI_API_KEY)
    }

@app.get("/api/schema/{database_name}")
async def get_database_schema_and_relationships(database_name: str, config: DatabaseConfig):
    """
    Endpoint to get database schema and relationships for debugging/inspection
    """
    connection = None
    try:
        connection = get_db_connection(config)
        
        # Get schema
        schema = get_table_schema(connection)
        schema_with_samples = get_sample_data(connection, schema)
        
        # Get relationships
        relationships = get_table_relationships(connection, schema_with_samples)
        
        return {
            "database": database_name,
            "tables": len(schema),
            "schema": schema_with_samples,
            "relationships": relationships,
            "relationship_summary": {
                "total_relationships": sum(len(rels) for rels in relationships.values()),
                "tables_with_relationships": len(relationships),
                "foreign_key_relationships": sum(1 for rels in relationships.values() 
                                               for rel in rels if rel.get('type') == 'foreign_key'),
                "inferred_relationships": sum(1 for rels in relationships.values() 
                                            for rel in rels if rel.get('type') == 'inferred')
            }
        }
        
    except Exception as e:
        error_msg = f"Error getting schema and relationships: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    import uvicorn
    print("\nStarting Enhanced Natural Language Query API with Relationship Detection...")
    print("Environment variables loaded:")
    print(f"- GEMINI_API_KEY: {'Set' if os.getenv('GEMINI_API_KEY') else 'Not set'}")
    print("\nNew Features:")
    print("- Automatic detection of foreign key relationships")
    print("- Inference of relationships based on naming conventions")
    print("- Enhanced SQL generation with relationship awareness")
    print("- Better JOIN query generation for multi-table queries")
    print("- Relationship information included in API responses")
    print("- New /api/schema endpoint for debugging relationships")
    print("\nPrevious Enhancements:")
    print("- Improved system prompt for better SQL generation")
    print("- Smart chart generation based on query intent")
    print("- Enhanced data validation for visualizations")
    print("- Added graph_generated flag in response")
    uvicorn.run(app, host="0.0.0.0", port=8000)