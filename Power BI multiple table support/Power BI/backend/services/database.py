import mysql.connector
import pyodbc
from typing import List, Dict, Any
from models.database import DatabaseConfig

class DatabaseService:
    def __init__(self, config: DatabaseConfig = None):
        self.config = config
        self.connection = None
        if config:
            self.connect()

    def connect(self):
        if not self.config:
            raise ValueError("Database configuration is required")
        
        try:
            if self.config.db_type.lower() == 'mysql':
                # MySQL connection
                self.connection = mysql.connector.connect(
                    host=self.config.server,
                    port=self.config.port,
                    user=self.config.username,
                    password=self.config.password,
                    database=self.config.database,
                    consume_results=True  # Ensure results are consumed
                )
                print(f"Successfully connected to MySQL database!")
            else:
                # SQL Server connection
                server = self.config.server
                if not server.startswith('tcp:'):
                    server = f'tcp:{server}'
                
                conn_str = (
                    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                    f"SERVER={server},{self.config.port};"
                    f"DATABASE={self.config.database};"
                    f"UID={self.config.username};"
                    f"PWD={self.config.password};"
                    "TrustServerCertificate=yes;"
                    "Encrypt=yes;"
                )
                self.connection = pyodbc.connect(conn_str)
            
            print(f"Successfully connected to {self.config.db_type} database!")
            
        except Exception as e:
            raise ValueError(f"Failed to connect to database: {str(e)}")

    def close(self):
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            finally:
                self.connection = None

    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        if not self.connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True, buffered=True)
            cursor.execute(query)
            results = cursor.fetchall()
            return results
        except Exception as e:
            raise ValueError(f"Failed to execute query: {str(e)}")
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass

    def get_table_columns(self, table_name: str) -> List[str]:
        if not self.connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True, buffered=True)
            cursor.execute(f"DESCRIBE {table_name}")
            columns = [row['Field'] for row in cursor.fetchall()]
            return columns
        except Exception as e:
            raise ValueError(f"Failed to get table columns: {str(e)}")
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass

    def get_sample_row(self, table_name: str) -> Dict[str, Any]:
        if not self.connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True, buffered=True)
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
            row = cursor.fetchone()
            return row if row else {}
        except Exception as e:
            raise ValueError(f"Failed to get sample row: {str(e)}")
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass

    def get_all_tables(self) -> List[str]:
        if not self.connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True, buffered=True)
            if self.config.db_type.lower() == 'mysql':
                cursor.execute("SHOW TABLES")
                tables = [list(row.values())[0] for row in cursor.fetchall()]
            else:
                cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
                tables = [row['TABLE_NAME'] for row in cursor.fetchall()]
            return tables
        except Exception as e:
            raise ValueError(f"Failed to get tables: {str(e)}")
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass

    def get_table_schema(self, table_name: str) -> Dict[str, Any]:
        if not self.connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True, buffered=True)
            if self.config.db_type.lower() == 'mysql':
                cursor.execute(f"DESCRIBE {table_name}")
                columns = cursor.fetchall()
                schema = {
                    'columns': [col['Field'] for col in columns],
                    'types': [col['Type'] for col in columns],
                    'null': [col['Null'] for col in columns],
                    'key': [col['Key'] for col in columns],
                    'default': [col['Default'] for col in columns]
                }
            else:
                cursor.execute(f"""
                    SELECT 
                        COLUMN_NAME,
                        DATA_TYPE,
                        IS_NULLABLE,
                        COLUMN_DEFAULT
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_NAME = '{table_name}'
                """)
                columns = cursor.fetchall()
                schema = {
                    'columns': [col['COLUMN_NAME'] for col in columns],
                    'types': [col['DATA_TYPE'] for col in columns],
                    'null': [col['IS_NULLABLE'] for col in columns],
                    'default': [col['COLUMN_DEFAULT'] for col in columns]
                }
            return schema
        except Exception as e:
            raise ValueError(f"Failed to get table schema: {str(e)}")
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass

    def get_table_sample(self, table_name: str, limit: int = 1) -> List[Dict[str, Any]]:
        if not self.connection:
            self.connect()
        
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True, buffered=True)
            cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
            return cursor.fetchall()
        except Exception as e:
            raise ValueError(f"Failed to get table sample: {str(e)}")
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass 