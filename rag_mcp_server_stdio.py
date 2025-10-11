
from mcp.server.fastmcp import FastMCP, Context
from resources import Resources
from prompt import Prompts
from tools import Tools

server_instructions = """
This MCP server provides search and document retrieval capabilities 
for deep research. Use the search tool to find relevant documents 
based on keywords, then use the fetch tool to retrieve complete 
document content with citations.
"""
mcp = FastMCP(name="fieldOn_rag", json_response=False, instructions=server_instructions)

tools = Tools()
prompts = Prompts()
resources = Resources()

@mcp.tool(title="Field On docs")
async def fieldOn_docs(question: str, ctx: Context) -> str:
    """ You help users understand how to manage roles like Account Administrator, Group Moderator, and Super Admins, as well as tasks such as creating forms, filling in required fields, selecting avatars, and related operations.

    Refer only to the context provided. If the context does not include the answer, respond with: 
    "I'm not sure based on the current information."

    Be concise and informative. Avoid assuming information not found in the context.
    Args:
        question: user questions on FieldOn documentation
    """
    await ctx.info(f"Info: {question}")
    return tools.fieldOn_response(question)

@mcp.tool(title="AG and P docs")
async def ag_and_p_docs(question: str, ctx: Context) -> str:
    """ You help users understand AG and P documentation, which includes AG and P field user features like geo-tagging
    form edit, weld functionality, MDPE pipe and Arraw device connection and related operations.

    Refer only to the context provided. If the context does not include the answer, respond with: 
    "I'm not sure based on the current information."

    Be concise and informative. Avoid assuming information not found in the context.
    Args:
        question: user questions on AG and P or AG&P documentation
    """
    ctx.info(f"Info : {question}")
    return tools.ag_and_p_response(question)

@mcp.tool(title="Book a table")
async def book_table(date: str, time: str, party_size: int, ctx: Context) -> str:
    """Collect user information through interactive prompts."""
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

if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        print("Server stopped by user.")
    except Exception as e:
        print(f"Error starting server: {e}")
    