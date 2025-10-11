def warn(*args, **kwargs):
    pass
import json
import warnings

from fastapi.responses import JSONResponse
warnings.warn = warn
warnings.filterwarnings('ignore')
import os
import ssl, certifi
from pydantic import BaseModel, Field
from mcp.server.fastmcp import Context
import certifi
from postgres.postgres_conn import PostgreSQL
# from sentence_transformers import SentenceTransformer
from langchain.utils.openai_functions import convert_pydantic_to_openai_function
from mcp.server.elicitation import (
    AcceptedElicitation, 
    DeclinedElicitation, 
    CancelledElicitation,
)
from openai import OpenAI

import mcp.types as types
import config

ssl_context = ssl.create_default_context(cafile=certifi.where())
# Define the directory to store papers
PAPER_DIR = "papers"
# Create the directory if it doesn't exist
os.makedirs(PAPER_DIR, exist_ok=True)

class fieldOn_docs(BaseModel):
    question: str = Field(description="user questions on FieldOn documentation")

class ag_and_p_docs(BaseModel):
    question: str = Field(description="user questions on FieldOn documentation")

class book_table(BaseModel):
    date: str = Field(description="date for table booking")
    time: str = Field(description="time of the table booking")
    party_size: str = Field(description="number of attendies")

class jokes(BaseModel):
    topic: str = Field(description="topic for the joke")


class BookingPreferences(BaseModel):
    """Schema for collecting user preferences."""
    checkAlternative: bool = Field(description="Would you like to check another date?")
    alternativeDate: str = Field(
        default="2024-12-26",
        description="Alternative date (YYYY-MM-DD)")
    
class databaseAccess(BaseModel):
    """ You are a PostgreSQL query assistant. 
        Your job is to convert natural language user questions into correct, secure, and optimized SQL queries using PostgreSQL syntax. 
        You will then use the appropriate tool call to execute the query or perform the requested action.

        1. When listing tables, include only **user-defined base tables**.
        2. Exclude all internal system schemas like 'pg_catalog' and 'information_schema'.
        3. Do not assume all tables are in the 'public' schema.
        4. Use: 
        SELECT table_schema, table_name 
        FROM information_schema.tables 
        WHERE table_type = 'BASE TABLE' 
            AND table_schema NOT IN ('pg_catalog', 'information_schema');
        when asked for a list of all user-defined tables.
        5. Always use `table_type = 'BASE TABLE'` to avoid views or temporary tables.
        6. When the user asks for time-based filters (e.g., "today", "yesterday", "last week"), Assume the relevant column is of type **timestamp**.
        7. Assume the date or time related queries use `timestamp` as a column name.
        8. Use CURRENT_DATE or NOW() appropriately:
            For "today": filter using timestamp::date = CURRENT_DATE
            For "yesterday": timestamp::date = CURRENT_DATE - INTERVAL '1 day'
            For "last 7 days": timestamp >= NOW() - INTERVAL '7 days'
    """
    query: str = Field(description="Postgresql queries for to get the details form database")
    
class DatabaseDetails(BaseModel):
    """Provide the login details for access"""
    host: str = Field(default="localhost", description="Host name")
    port: str = Field(default="5432", description="Port number")
    username: str = Field(description="Username to get the access")
    password: str = Field(description="Password for autherized access")
    database: str = Field(default="hf_vector", description="Database name")

class DatabaseQuery(BaseModel):
    query: str = Field(default="", description="Postgresql database query")
    
    @classmethod
    def with_default_query(cls, default_query: str) -> type['DatabaseQuery']:
        """Dynamically create a subclass with the default query value"""
        class DynamicDatabaseQuery(cls):
            query: str = Field(default=default_query, description="Postgresql database query")
        return DynamicDatabaseQuery

class Tools():
    def __init__(self):
        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        pass

    async def get_embedding(self, text: str) -> list:
        """Get embeddings using OpenAI's embedding model"""
        response = self.openai_client.embeddings.create(
            model=config.OPENAI_EMBEDDING_MODEL,  # e.g., "text-embedding-3-small"
            input=text
        )
        return response.data[0].embedding

    def openAi_funcs(self):
        # Convert all Pydantic tools to OpenAI function format
        tool_classes = [
            fieldOn_docs,
            ag_and_p_docs,
            book_table,
            jokes,
            databaseAccess
        ]
        
        # Wrap each function with type="function"
        tool_map = [
            {
                "type": "function",
                "function": convert_pydantic_to_openai_function(tool)
            }
            for tool in tool_classes
        ]
        return tool_map

    async def book_table(self, date: str, time: str, party_size: int, ctx: Context) -> str:
        """Book a table with date availability check."""
        if date == "2024-12-25":
            print(f"Date {date} is unavailable for booking.")
            result = await ctx.elicit(
                message=f"No tables available for {party_size} on {date}. Would you like to try another date?",
                schema=BookingPreferences,
            )
            print("Result : ", result)

            match result:
                case AcceptedElicitation(data=data):
                    if data.checkAlternative:
                        return f"[SUCCESS] Booked for {data.alternativeDate}"
                    else:
                        return "[Accepted] booking made on available date."
                case DeclinedElicitation():
                    return "[Declined] No booking made"
                case CancelledElicitation():
                    return "[Cancelled] Booking cancelled"

        # Otherwise, fallback if the date is available
        return f"[SUCCESS] Booked for {date}"
    
    async def databaseRequest(self, ctx: Context):
        result = await ctx.elicit(
            message=f"we need credentials to get access!",
            schema=DatabaseDetails,
        )
        match result:
            case AcceptedElicitation(data=data):
                if data.username and data.password:
                    database = PostgreSQL(
                                host=data.host,
                                port=data.port,
                                user=data.username,
                                password=data.password,
                                database=data.database
                            )
                    try:
                        return database
                    except Exception as e:
                        res = "Error something went wrong"
                        raise res
                else:
                    raise "Try again"
            case DeclinedElicitation():
                raise "Declined"
            case CancelledElicitation():
                raise "Cancelled"

        # Otherwise, fallback if the date is available
        raise f"Something went wrong"

    
    async def databaseAccess(self, query: str, ctx: Context ) -> str:
        """
        You are a PostgreSQL query assistant. 
        Your job is to convert natural language user questions into correct, secure, and optimized SQL queries using PostgreSQL syntax.
        You will then use the appropriate tool call to execute the query or perform the requested action.
        Instructions:
        1) do not include postgreSQL internal system tables.
        2) include only user defined tables.
        """
        result = await ctx.elicit(
            message=f"we need credentials to get access!",
            schema=DatabaseDetails,
        )
        match result:
            case AcceptedElicitation(data=data):
                if data.username and data.password:
                    database = PostgreSQL(
                                host=data.host,
                                port=data.port,
                                user=data.username,
                                password=data.password,
                                database=data.database
                            )
                    try: 
                        res = await self.executeQuery(defaultQuery=query, database=database, ctx=ctx)
                        # rows = database.fetch_all(query=query)
                        # res = rows

                    except Exception as e:
                        res = "Error something went wrong"
                    return res
                else:
                    return "Try again"
            case DeclinedElicitation():
                return "Declined"
            case CancelledElicitation():
                return "Cancelled"

        # Otherwise, fallback if the date is available
        return f"Something went wrong"
    
    async def executeQuery(self, defaultQuery: str, database, ctx: Context) -> str:
        print(f"Query : {defaultQuery}")

        # Create a dynamic schema with the default query
        QuerySchema = DatabaseQuery.with_default_query(defaultQuery)

        result = await ctx.elicit(
            message=f"Please validate the Postgres SQL query before execute",
            schema=QuerySchema
        )
        match result:
            case AcceptedElicitation(data=data):
                if data.query:
                    try: 
                        rows = database.fetch_all(query=data.query)
                        res = json.dumps(rows, indent=4)
                        print("Result")
                    except Exception as e:
                        print("Error 1")
                        res = "Error something went wrong"
                return res
            case DeclinedElicitation():
                print("Error 2")
                return "Declined"
            case CancelledElicitation():
                print("Error 2")               
                return "Cancelled"
        # Otherwise, fallback if the date is available
        return f"Something went wrong"
    
    def jokes(self, topic, ctx: Context):

        return topic       
    
