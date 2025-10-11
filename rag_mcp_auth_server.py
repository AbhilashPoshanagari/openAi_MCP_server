from mcp.server.auth.provider import validate_access_token
from fastapi import Depends, HTTPException, status
from simple_auth_provider import SimpleOAuthProvider, SimpleAuthSettings
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


import sys
import contextlib

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from mcp.types import SamplingMessage, TextContent
from starlette.applications import Starlette
from starlette.routing import Mount
from mcp.server.fastmcp import FastMCP, Context
from resources import get_available_folders, get_topic_papers
from prompt import generate_search_prompt
from tools import fieldOn_response, ag_and_p_response, book_table
from starlette.applications import Starlette
import uvicorn
from starlette.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
# from langchain_core.utils.function_calling import convert_to_openai_function
from typing import List, TypedDict
from langchain.prompts import MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain.agents.output_parsers import OpenAIFunctionsAgentOutputParser
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import openai
from conv_to_open_ai_funcs import convert_mcp_tools

# Load environment variables
load_dotenv()
server_instructions = """
This MCP server provides search and document retrieval capabilities 
for deep research. Use the search tool to find relevant documents 
based on keywords, then use the fetch tool to retrieve complete 
document content with citations.
"""

mcp = FastMCP(name="fieldOn_rag", host = "0.0.0.0",
                port = 3000, json_response=False, 
                stateless_http=False, instructions=server_instructions)

# Initialize authentication
auth_settings = SimpleAuthSettings()
auth_provider = SimpleOAuthProvider(
    settings=auth_settings,
    auth_callback_url="http://localhost:3000/auth/callback",
    server_url="http://localhost:3000"
)

@mcp.tool()
async def fieldOn_response_tool(
    question: str,
    ctx: Context,
    token: AccessToken = Depends(validate_access_token)
) -> str:
    await ctx.info(f"Info: {question}")
    return fieldOn_response(question)

# Create a combined lifespan to manage both session managers
# @contextlib.asynccontextmanager
# async def lifespan(app: Starlette):
#     async with contextlib.AsyncExitStack() as stack:
#         await stack.enter_async_context(mcp.session_manager.run())
#         yield

@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        # Register a demo client
        await auth_provider.register_client(
            OAuthClientInformationFull(
                client_id="demo_client",
                client_secret="demo_secret",
                redirect_uris=["http://localhost:4200/auth/callback"],
                scope=["user"],
                grant_types=["authorization_code"]
            )
        )
        
        await stack.enter_async_context(mcp.session_manager.run())
        yield

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
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*", "Authorization"],  # Add Authorization header
    expose_headers=["mcp-session-id", "Authorization"],
    allow_credentials=True
)

# Add these routes before your existing routes
@app.route("/auth/login", methods=["GET"])
async def auth_login(request: Request):
    """OAuth login endpoint"""
    # Extract OAuth parameters from query
    client_id = request.query_params.get("client_id")
    redirect_uri = request.query_params.get("redirect_uri")
    state = request.query_params.get("state")
    scope = request.query_params.get("scope")
    
    if not all([client_id, redirect_uri, state]):
        raise HTTPException(status_code=400, detail="Missing required parameters")
    
    # Get client (in a real implementation, validate the client)
    client = await auth_provider.get_client(client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Invalid client")
    
    # Generate authorization URL
    auth_url = await auth_provider.authorize(
        client=client,
        params=AuthorizationParams(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope=scope.split(" ") if scope else None
        )
    )
    
    return RedirectResponse(url=auth_url)

@app.route("/auth/callback", methods=["GET"])
async def auth_callback_page(request: Request):
    """Display login page"""
    state = request.query_params.get("state")
    return await auth_provider.get_login_page(state)

@app.route("/auth/callback", methods=["POST"])
async def auth_callback_submit(request: Request):
    """Handle login form submission"""
    return await auth_provider.handle_login_callback(request)

@app.route("/auth/token", methods=["POST"])
async def auth_token(request: Request):
    """OAuth token endpoint"""
    form_data = await request.form()
    grant_type = form_data.get("grant_type")
    code = form_data.get("code")
    redirect_uri = form_data.get("redirect_uri")
    client_id = form_data.get("client_id")
    
    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant type")
    
    # Get client (in a real implementation, validate client secret too)
    client = await auth_provider.get_client(client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Invalid client")
    
    # Exchange code for token
    try:
        auth_code = await auth_provider.load_authorization_code(client, code)
        if not auth_code:
            raise HTTPException(status_code=400, detail="Invalid authorization code")
        
        token = await auth_provider.exchange_authorization_code(client, auth_code)
        return JSONResponse(token.dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

    # Protected version of your existing routes
@mcp.custom_route("/open_ai_func", methods=["GET"])
async def health_check(
    request: Request,
    token: AccessToken = Depends(validate_access_token)
) -> Response:
    tools = await mcp.list_tools()
    function_defs = convert_mcp_tools(tools)
    return JSONResponse({"status": "200", "open_ai_funcs": function_defs})

@app.route("/openAi_funcs", methods=["GET"])
async def get_openai_functions(
    request: Request,
    token: AccessToken = Depends(validate_access_token)
) -> JSONResponse:
    tools = await mcp.list_tools()
    function_defs = convert_mcp_tools(tools)
    return JSONResponse({
        "status": "OK",
        "openai_functions": function_defs
    })

if __name__ == "__main__":
    try:
        # Defaults
        transport = "streamable-http"     # "sse", "streamable-http", "stdio"
        # Parse optional CLI args
        if len(sys.argv) > 1:
            transport = sys.argv[1]
        # mcp.run(transport=transport)
        uvicorn.run(app, host="0.0.0.0", port=3000)
    except KeyboardInterrupt:
        print("Server stopped by user.")
        mcp.session_manager.close()
    except Exception as e:
        print(f"Error starting server: {e}")
        mcp.session_manager.close()
        sys.exit(1)

