from typing import List, Dict, Any
from fastapi import Request
from fastapi.responses import JSONResponse
import json

def convert_mcp_to_openai_function(mcp_tool) -> Dict[str, Any]:
    """Convert a single MCP tool to OpenAI function format.
    
    Args:
        mcp_tool: The MCP tool to convert
        
    Returns:
        Dictionary representing the OpenAI function format
    """
    tool_dict = mcp_tool._asdict() if hasattr(mcp_tool, '_asdict') else dict(mcp_tool)
    
    function_def = {
        "name": tool_dict["name"],
        "description": tool_dict.get("description", ""),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
    
    # Process input schema if available
    input_schema = tool_dict.get("inputSchema", {})
    if input_schema:
        for param_name, param_def in input_schema.get("properties", {}).items():
            param_info = {
                "type": param_def.get("type", "string"),
                "description": param_def.get("description", param_def.get("title", ""))
            }
            if "enum" in param_def:
                param_info["enum"] = param_def["enum"]
            function_def["parameters"]["properties"][param_name] = param_info
        
        if "required" in input_schema:
            function_def["parameters"]["required"] = input_schema["required"]
    
    return {"type": "function", "function": function_def}

def convert_mcp_tools(mcp_tools: List) -> List[Dict[str, Any]]:
    """Convert a list of MCP tools to OpenAI functions format.
    
    Args:
        mcp_tools: List of MCPTool objects
        
    Returns:
        List of OpenAI function definitions
    """
    return [convert_mcp_to_openai_function(tool) for tool in mcp_tools]

# Example usage with your tools
if __name__ == "__main__":
    # Sample MCP tools (simplified from your error message)
    mcp_tools = [
        {
            "name": "fieldOn_response_tool",
            "description": "Help with FieldOn documentation questions",
            "inputSchema": {
                "properties": {"question": {"type": "string"}},
                "required": ["question"]
            }
        },
        {
            "name": "ag_and_p_response_tool",
            "description": "Help with AG and P documentation",
            "inputSchema": {
                "properties": {"question": {"type": "string"}},
                "required": ["question"]
            }
        }
    ]
    
    # Convert the tools
    openai_tools = convert_mcp_tools(mcp_tools)
    print("Converted OpenAI Tools:")
    print(json.dumps(openai_tools, indent=2))