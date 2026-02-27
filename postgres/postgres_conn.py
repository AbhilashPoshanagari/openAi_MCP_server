import json
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from psycopg2.extensions import register_adapter, AsIs, adapt
from contextlib import contextmanager

load_dotenv()

class PostgreSQL():
    def __init__(self, host: str, database: str, user: str, password: str, port: int):
        self.config = {
        'host': host,
        'database': database,
        'user': user,
        'password': password, # Replace the password with the password of your postgres instance
        'port': port
        }
        self.conn = None
        self._initialize_database()
        # register_adapter(dict, self.adapt_dict)

    def __call__(self):
        if self.conn is None or self.conn.closed:
            try:
                self.conn = psycopg2.connect(**self.config)
                psycopg2.extras.register_default_jsonb(loads=json.loads, globally=True)
                print("PostgreSQL connection established.")
            except Exception as e:
                print("Failed to connect to PostgreSQL:", e)
                self.conn = None
        return self.conn
    
    # Register adapter to automatically convert dict to JSON
    # def adapt_dict(self, d):
    #     return psycopg2.extensions.AsIs("'%s'::jsonb" % json.dumps(d))
    @contextmanager
    def get_cursor(self):
        """Context manager for database cursor"""
        conn = self()
        if conn is None:
            raise Exception("Database connection not available")
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
    
    def _initialize_database(self):
        """Initialize database with required tables"""
        try:
            conn = self()
            if conn:
                with conn.cursor() as cursor:
                    # Create users table
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            id SERIAL PRIMARY KEY,
                            username VARCHAR(50) UNIQUE NOT NULL,
                            email VARCHAR(100) UNIQUE NOT NULL,
                            password_hash VARCHAR(255) NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_login TIMESTAMP,
                            is_online BOOLEAN DEFAULT false,
                            call_status VARCHAR(20) DEFAULT 'available',
                            refresh_token VARCHAR(500),
                            token_expiry TIMESTAMP
                        )
                    """)
                    
                    # Create indexes
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_users_username 
                        ON users(username)
                    """)
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_users_email 
                        ON users(email)
                    """)
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_users_online 
                        ON users(is_online) WHERE is_online = true
                    """)
                    
                    conn.commit()
                    print("Database tables initialized successfully.")
        except Exception as e:
            print(f"Failed to initialize database: {e}")
    
    def execute(self, query: str, *args):
        conn = self()
        results = None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                if cursor.description:  # Query returns results (e.g., SELECT)*
                    results = cursor.fetchall()
                else:
                    conn.commit()  # For INSERT, UPDATE, DELETE
        except Exception as e:
            print("Query execution failed:", e)
            if conn:
                conn.rollback()
        return results
    
    def create_update_insert(self, query:str, params: tuple = ()):
        conn = self()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if len(params) > 0:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                conn.commit()  # For INSERT, UPDATE, DELETE
        except Exception as e:
            print("Query execution failed:", e)
            if conn:
                conn.rollback()
        return None        
    
    
    def fetch_all(self, query: str, params: tuple = ()) -> list[dict]:
        """
        Execute SELECT query and return all rows as list of dicts.
        """
        conn = self()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            print("Query fetch_all failed:", e)
            return []

    def fetch_one(self, query: str, params: tuple = ()) -> dict | None:
        """
        Execute SELECT query and return first row as a dict.
        """
        conn = self()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchone()
        except Exception as e:
            print("Query fetch_one failed:", e)
            return None
        
    def insert_and_get_id(self, query: str, params: tuple = ()) -> int | None:
        """Insert a record and return the generated ID"""
        conn = self()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query + " RETURNING id", params)
                result = cursor.fetchone()
                conn.commit()
                return result['id'] if result else None
        except Exception as e:
            print("Insert failed:", e)
            if conn:
                conn.rollback()
            return None
        
 # Create a global instance
# postgres_db = PostgreSQL()
    