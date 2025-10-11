import sys
import contextlib
import logging
import mcp.types as types
import anyio
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.routing import Mount
from mcp.server.fastmcp import FastMCP, Context
from resources.resources import Resources
from prompts.prompt import Prompts
from tools.tools import Tools
from starlette.applications import Starlette
from pydantic import BaseModel, Field
import uvicorn
from starlette.middleware.cors import CORSMiddleware
from mcp.types import ResourceTemplateReference, Completion
import config
import click

server_instructions = """
This MCP server provides search and document retrieval capabilities 
for deep research. Use the search tool to find relevant documents 
based on keywords, then use the fetch tool to retrieve complete 
document content with citations.
"""

# Configure logging
logger = logging.getLogger(__name__)

mcp = FastMCP(name=config.MCP_SERVER_NAME, host = config.MCP_HOST, debug = True,
                port = config.MCP_PORT, json_response=False,
                stateless_http=False, instructions=server_instructions)

tools = Tools()
prompts = Prompts()
resources = Resources()

class LongRunningTaskOutput(BaseModel):
    message: str
    progress: float
    status: str | None = None

class UserInfo(BaseModel):
    username: str = Field(description="FieldOn App mobile username")
    password: int = Field(description="FieldOn App mobile password")

@mcp.tool(title="Database queries", description="""You are a PostgreSQL query assistant. 
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
    """, annotations={
         "query": {"description": "The natural language question to be converted into a SQL query."}
         })
async def databaseAccess(query: str, ctx: Context):
  
    return await tools.databaseAccess(query, ctx)

@mcp.tool(title="Streaming notification", description="long running task",
          annotations={
              "interval": {"description": "Interval in seconds between notifications"},
              "count": {"description": "Total number of notifications to send"},
              "caller": {"description": "Identifier for the caller or task"}
          })
async def notificationsWithResumability(interval: int, count: int, caller: str,  ctx: Context) -> list[types.ContentBlock]:
        # Send the specified number of notifications with the given interval
        for i in range(count):
            notification_msg = (
                f"[{i + 1}/{count}] Event from '{caller}' - "
                f"Use Last-Event-ID to resume if disconnected"
            )
            await ctx.session.send_log_message(
                level="info",
                data=notification_msg,
                logger="notification_stream",
                related_request_id=ctx.request_id,
            )
            logger.debug(f"Sent notification {i + 1}/{count} for caller: {caller}")
            print(f'Sent notification {i + 1}/{count} for caller: {caller}')
            if i < count - 1:  # Don't wait after the last notification
                await anyio.sleep(interval)

        # This will send a resource notificaiton though standalone SSE
        return [
            types.TextContent(
                type="text",
                text=(
                    f"Sent {count} notifications with {interval}s interval"
                    f" for caller: {caller}"
                ),
            )
        ]

@mcp.tool(title="Book a table", description="Book a table at a restaurant by providing date, time, and party size.",
          annotations={
              "date": {"description": "Date for the reservation in DD-MM-YYYY format"},
              "time": {"description": "Time for the reservation in HH:MM format"},
              "party_size": {"description": "Number of people for the reservation"}
          })
async def book_table(date: str, time: str, party_size: int, ctx: Context) -> str:
        return await tools.book_table(date, time, party_size, ctx)

@mcp.resource("papers://folders", title="Resources")
def available_folders() -> str:
        """
        List all available topic folders in the papers directory.
        This resource provides a simple list of all available topic folders.
        """
        return resources.get_available_folders()


@mcp.resource("papers://{topic}", title="Topic based list")
def topic_papers(topic: str) -> str:
        """
        Get detailed information about papers on a specific topic.
        Args:
            topic: The research topic to retrieve papers for
        """
        return resources.get_topic_papers(topic)

@mcp.prompt(title="Acadamic search prompt")
def search_prompt(topic: str, num_papers: int = 5) -> str:
    """Generate a prompt for Claude to find and discuss academic papers on a specific topic."""
    return prompts.generate_search_prompt(topic, num_papers)

@mcp.completion()
async def handle_completion(ref, argument, context):
    if isinstance(ref, ResourceTemplateReference):
        # Return completions based on ref, argument, and context
        return Completion(values=["option1", "option2"])
    return None

# Create a combined lifespan to manage both session managers
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield

@mcp.custom_route("/openAi_funcs", methods=["GET"])
async def health_check(request: Request) -> Response:
    functions = tools.openAi_funcs()
    return JSONResponse({"status":200,  "openai_functions": functions})

# Create the Starlette app and mount the MCP servers
app = Starlette(
    routes=[
        Mount("/fieldOn_rag", mcp.streamable_http_app())
    ],
    lifespan=lifespan
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify: ["http://localhost:4200"]
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["mcp-session-id"]
)

@click.command()
@click.option("--host", default="0.0.0.0", help="Enter host name")
@click.option("--port", default=8100, help="Enter port number")
def startServer(host, port):
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    try:
       startServer()
    except KeyboardInterrupt:
        print("Server stopped by user.")
        mcp.session_manager.close()
    except Exception as e:
        print(f"Error starting server: {e}")
        mcp.session_manager.close()
        sys.exit(1)
    