import json
import re
import sys
import contextlib
import logging
from typing import Any, Dict, List, Optional
import mcp.types as types
import anyio
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from layoutSchema.api_calls import RestApiHelper
from layoutSchema.form_shema import DynamicFormGenerator, FormResponse
from layoutSchema.generic_layout import TableFormat, TableLayout
from starlette.routing import Mount
from mcp.server.fastmcp import FastMCP, Context
from layouts.map_layout import MapFeature, MapFeatures, MapLayout
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
import time

def is_colab():
    """Detect if code runs inside Google Colab."""
    try:
        import google.colab
        return True
    except ImportError:
        return False

def setup_ngrok(port: int):
    """If running in Colab, start ngrok and return public URL."""
    try:
        from pyngrok import ngrok, conf
        # from google.colab import userdata
    except ImportError:
        print("pyngrok not installed or not in Colab; skipping ngrok.")
        return None

    try:
        # token = userdata.get("ngrok_token")
        token = config.NGROK_AUTHTOKEN
        # if not token:
        #     print("No ngrok token found in Colab userdata. Please set it using:")
        #     print("    from google.colab import userdata")
        #     print("    userdata.set('ngrok_token', 'YOUR_TOKEN')")
        #     return None
        # conf.get_default().auth_token = token
        # ngrok.set_auth_token(token)
        # time.sleep(2)

        public_url = ngrok.connect(port)
        print(f"ngrok tunnel active: {public_url}")
        return public_url
    except Exception as e:
        print(f"Failed to start ngrok: {e}")
        return None

server_instructions = """
# SYSTEM INSTRUCTIONS FOR LAYOUT MCP SERVER
You are a Layout Visualization Assistant that converts user requests into interactive visual components using specific layout tools.

## AVAILABLE LAYOUT TYPES
1. **Table Layout**: For structured data presentation (rows/columns)
2. **Map Layout**: For geographical/coordinate-based visualization  
3. **Form Layout**: For dynamic form generation and data collection
4. **Button Layout**: For actions, navigation, and external links

## CORE PRINCIPLES
- ALWAYS output ONLY valid JSON function calls for the appropriate tool
- NEVER include explanations, markdown, or natural language in responses
- Each layout type has specific trigger conditions
- Format ALL parameters according to the expected data structures

## TOOL SELECTION GUIDELINES

### When to use TABLE_LAYOUT_TOOL:
- User mentions "table", "spreadsheet", "grid", "list of records"
- Data contains structured fields, rows, columns
- User asks for "show in table", "tabular format", "data table"
- Response includes arrays of objects with similar keys

### When to use MAP_LAYOUT_TOOL:
- User mentions locations, addresses, coordinates, places
- User says "show on map", "visualize locations", "where is", "near me"
- Data contains latitude/longitude pairs, addresses
- User asks for geographical representation
- each GeoJSON Feature must have geometry

### When to use FORM_LAYOUT_TOOL:
- User wants to "create a form", "fill out information", "collect data"
- User mentions specific form types (inspection, survey, report)
- Need dynamic form generation with validation
- Form submission required

### When to use BUTTON_LAYOUT_TOOL:
- User wants to "open", "go to", "navigate to", "click here"
- User asks for external links, actions, or deep links
- Need interactive buttons for navigation
- Mobile app deeplinking required

## OUTPUT FORMAT RULES
- Output must be ONLY a JSON function call object
- No code fences, no markdown, no explanations
- Match exact parameter names and types from tool definitions
- Validate data structures before calling
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

@mcp.tool(title="Table view", description=f"""You are an expert data analyst specializing in infrastructure and utility network data analysis.

        Your task is to:
        Your ONLY valid output format is a JSON function call for the tool `table_layout_tool`.  
        Return ONLY a function_call object.
          
        ### Table Interpretation Requirements
        When the data contains table-like structures (e.g., rows, objects, structured fields):
        1. **Identify the table structure** detect if the data resembles a table or list of records.  
        2. **Identify the table name** and generate a meaningful, human-friendly title.  
        3. **Identify the column names** based on the keys or attributes found.  
        4. **Separate and present**:
        - Table name (as a title)  
        - Column names  
        - Data for each column (in markdown table format)
        call the table_layout_tool tool or function with the extracted table name, column names, and data.""",
   annotations={
            "table_name": {
                "type": "string",
                "description": "based on report give us a table name"
            },
            "column_names":{
                "type": "list",
                "description": "list of columns in the table"
            },
            "data": {
                "type": "list[list[int | bool | str]]",
                "description": "list of each row and column values" 
            }
        })
def table_layout_tool(table_name: str, column_names: list[str], data: list[list[str]] ): 

    table_data = TableFormat(table_name=table_name, column_names=column_names, data=data)
    table_layout = {"layouts": [TableLayout(type="table",
                               data= table_data)]
                               }
    return table_layout

@mcp.tool(
    title="Map Visualization",
    description="""You are a geospatial data specialist for visualizing location-based data.

    Use this tool when:
    1. User mentions locations, addresses, coordinates, or places
    2. User wants to see data on a map
    3. Data contains latitude/longitude pairs, addresses, or geospatial references
    4. User asks for "show on map", "visualize locations", "where is", "near me"

    ### Map Creation Requirements
    1. **Identify geographical elements**: Extract any addresses, coordinates, place names
    2. **Determine map focus**: Calculate center point from provided locations
    3. **Set appropriate zoom**: Choose zoom level based on location density
    4. **Style features appropriately**: Use meaningful colors for different feature types

    Example feature sturcture: [{
                "type": "Feature",
                "id": "rest_1",
                "properties": {
                    "name": "Third Wave Coffee",
                    "type": "Cafe",
                    "address": "Knowledge City, Raidurg"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [78.37385, 17.43352]
                }
            }]
    
    Call the map_layout_tool with extracted features, center, and zoom.""",
    annotations={
        "features": {
            "type": "List",
            "description": "List of map features with id, name, type, coordinates, properties, and optional style as a string format"
        },
        "map_title": {
            "type": "string",
            "description": "Optional title for the map",
        },
        "wms_layers": {
            "type": "List[Dict]",
            "description": "wms or osm layer setup"
        }
    }
)
def map_layout_tool(
    features: List[MapFeature],
    map_title: str,
    wms_layers: List[Dict] = None ) -> Dict[str, Any]:

    # Features are already MapFeature objects - convert to dicts
    feature_dicts = [feature.to_dict() for feature in features]

    # Create map data structure
    map_data = {
        "features": feature_dicts,
    }

    if map_title:
        map_data["title"] = map_title
    
    if wms_layers:
        map_data["wmsLayers"] = wms_layers
    else:
        map_data["wmsLayers"] = [{
            "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "layers": "osm",
            "attribution": "© OpenStreetMap contributors"
        }]
    print(f"Map data : {map_data}")
    return {
        "layouts": [{
            "type": "map",
            "data": map_data
        }]
    }

@mcp.tool(
    title="Generate Dynamic Form",
    description="Generate a form layout from form widgets configuration",
    annotations={
        "form_id": {
            "type": "str",
            "description": "Form configuration data containing formWidgets"
        },
        "submit_tool_name": {
            "type": "string", 
            "description": "Name of the tool to call on form submission"
        }
    }
)
def generate_dynamic_form(
    form_id: str = "e2f293e90000000000000000",
    fieldOn_access_token: str = ""
) -> Dict[str, Any]:
    """
    Generate a dynamic form layout from form widgets configuration.
    
    Args:
        form_id: The form configuration data containing formWidgets
        fieldOn_access_token: access token for authentication
    """
    try:
        # Validate input data
        # form_response = FormResponse(**form_data)
        form_schema_url = f"https://dev.mobile-springboard.digital.trccompanies.com/api/v1/forms/formSkeleton/{form_id}/null/True/null/null/null/null/64898d0cc2fd807b50602703/openform"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"{fieldOn_access_token}",
            "Accept": "application/json",
        }
        fieldOn_form = RestApiHelper.get_request(url=form_schema_url, headers=headers)
        # -------------------------------------------
        # 2. Collect missing types before validation
        # -------------------------------------------
        ALLOWED_TYPES = {
                "textBox", "status", "dropdown", "select",
                "checkbox", "radio", "textArea", "number",
                "date", "email"
            }

        raw_widgets = fieldOn_form.get("data", {}).get("formWidgets", [])
        missing_types: set[str] = set()
        valid_widgets = []
        # --------------------------------------------------
        # 3. Filter OUT invalid widgets BEFORE validation
        # --------------------------------------------------
        for widget in raw_widgets:
            wtype = widget.get("type")

            if wtype not in ALLOWED_TYPES:
                missing_types.add(str(wtype))
                # SKIP — remove from list so Pydantic never sees it
                continue

            valid_widgets.append(widget)

        # apply sanitized widgets back to the structure
        fieldOn_form["data"]["formWidgets"] = valid_widgets
        if missing_types:
            comment = (
                "The following widget types were not supported and were removed: "
                + ", ".join(sorted(missing_types))
            )
        else:
            comment = "All widget types recognized successfully."
        form_response = FormResponse(**fieldOn_form)

        # form_response = FormResponse(**fieldOn_form)
        form_widgets = form_response.data.formWidgets

        # Debug formInfo access
        form_info = form_response.data.formInfo

        # Create dynamic form model
        DynamicForm = DynamicFormGenerator.create_dynamic_form_model(form_widgets)
        # Generate JSON Schema for the form
        form_schema = DynamicForm.model_json_schema()
        print(f"Form schema : {form_schema}")
        
        # Enhance schema with form metadata
        form_schema["title"] = form_response.data.formInfo.name
        form_schema["description"] = form_response.data.formInfo.description or f"Form created by {form_response.data.formInfo.createdBy}"
        
        # Add widget-specific metadata to properties
        for widget in form_widgets:
            field_name = DynamicFormGenerator.sanitize_field_name(widget.label or widget.id)
            print("Field Name : ", json.dumps(field_name, indent=2))
            if field_name in form_schema["properties"]:
                # Add widget type information
                form_schema["properties"][field_name]["widgetType"] = widget.type.value
                form_schema["properties"][field_name]["originalId"] = widget.id
                form_schema["properties"][field_name]["position"] = widget.position
                
                # Add options if available
                if widget.options:
                    form_schema["properties"][field_name]["options"] = [
                        {"displayValue": opt.displayValue, "value": opt.value} 
                        for opt in widget.options
                    ]
        
        formLayout = { 
            "layouts": [{
                "type": "form",
                "data": {
                    "title": form_info.name,
                    "schema": form_schema,  # Direct schema for elicitation component
                    "metadata": {
                        "form_id": getattr(form_info, '_id', form_info.id),
                        "createdBy": form_info.createdBy,
                        "version": form_info.version,
                        "description": form_info.description,
                        "totalFields": len(form_widgets),
                        "form_name": form_info.name,
                        "comment": comment
                    },
                    "actions": {
                        "submit": {
                            "type": "tool",
                            "title": "Submit",
                            "tool_name": "add_record",
                            "description": f"Submit {form_response.data.formInfo.name} form",
                            "params": {
                                "form_data": {
                                    "type": "json"
                                },
                                "form_id": {
                                    "type": "metadata",
                                    "field": "form_id"
                                    },
                                "form_name": {
                                    "type": "metadata",
                                    "field": "form_name"
                                }
                            }
                        },
                        "cancel": {
                            "type": "cancel",
                            "title": "Cancel",
                            "description": "Cancel form submission"
                        }
                    }
                }
            }
        ]
        }
        
        return formLayout
        
    except Exception as e:
        return {
            "type": "error",
            "message": f"Error generating form: {str(e)}",
            "details": str(e)
        }

@mcp.tool(
    title="Action Button Creator",
    description="""You are an action specialist for creating interactive buttons and links.

    Use this tool when:
    1. User wants to perform an external action
    2. User needs navigation to external resources
    3. User asks for "click here", "open", "go to", "navigate to", "visit"
    4. User wants to "launch", "start", "access", "connect to"
    5. Deep linking to mobile apps or specific URLs is needed

    Your ONLY valid output format is a JSON function call for the tool `button_layout_tool`.
    Do NOT return python code. Do NOT return markdown. Do NOT explain anything.
    Do NOT wrap the output in code fences. Do NOT speak in natural language.
    Return ONLY a function_call object.

    ### Button Creation Requirements
    1. **Identify action type**: Determine if it's a link, deep link, or action
    2. **Create descriptive label**: Button text should clearly indicate the action
    3. **Set appropriate URL**: Ensure the link is valid and relevant
    4. **Consider deep linking**: Add deeplink for mobile app integration when appropriate
    
    Call the button_layout_tool with button configuration.""",
    annotations={
        "button_title": {
            "type": "string",
            "description": "Button display text"
        },
        "link": {
            "type": "string",
            "description": "URL or action link for the button"
        },
        "deeplink": {
            "type": "string",
            "description": "Optional deep link for mobile apps",
        }
    }
)
def button_layout_tool(
    button_title: str,
    link: str,
    deeplink: str = ""
) -> Dict[str, Any]:
    """
    Create a button layout for actions and navigation.
    
    Example usage:
    User: "Give me a link to Google Maps for this location"
    LLM: Calls button_layout_tool with:
      title: "Open in Google Maps"
      link: "https://www.google.com/maps/search/?api=1&query=37.7749,-122.4194"
      deeplink: "comgooglemaps://?center=37.7749,-122.4194&zoom=14"
    """
    
    button_data = {
        "title": button_title,
        "link": link
    }
    
    if deeplink:
        button_data["deeplink"] = deeplink
    
    button_layout = {
        "layouts": [{
            "type": "button",
            "data": button_data
        }]
    }
    
    return button_layout



# Alternative: Get all features
@mcp.tool()
def kanban_testing(work_title: str):
    """Get all map features in layout format"""
    kanban_board = {
  "type": "kanban",
  "data": {
    "board_title": "Project Development Tasks",
    "board_id": "project-123",
    "columns": [
      {
        "id": "backlog",
        "title": "Backlog",
        "status": "todo",
        "wip_limit": 10,
        "color": "#FF6B6B",
        "icon": "backlog",
        "cards": [
          {
            "id": "task-001",
            "title": "Implement user authentication",
            "description": "Add JWT-based authentication system",
            "assignee": "John Doe",
            "due_date": "2024-02-15",
            "tags": ["backend", "security", "high-priority"],
            "priority": "high",
            "attachments": [
              {
                "name": "auth_spec.pdf",
                "url": "/docs/auth_spec.pdf",
                "type": "pdf"
              }
            ],
            "comments": 3,
            "metadata": {
              "epic": "User Management",
              "story_points": 5,
              "created_by": "PM"
            }
          }
        ]
      },
      {
        "id": "in_progress",
        "title": "In Progress",
        "status": "in_progress",
        "wip_limit": 4,
        "color": "#4ECDC4",
        "icon": "progress",
        "cards": [
          {
            "id": "task-002",
            "title": "Design dashboard UI",
            "description": "Create responsive dashboard components",
            "assignee": "Jane Smith",
            "due_date": "2024-02-10",
            "tags": ["frontend", "design"],
            "priority": "medium",
            "comments": 8
          }
        ]
      },
      {
        "id": "review",
        "title": "Review",
        "status": "review",
        "color": "#FFD166",
        "icon": "review",
        "cards": [
          {
            "id": "task-003",
            "title": "API documentation",
            "description": "Write OpenAPI documentation",
            "assignee": "Alex Johnson",
            "due_date": "2024-02-05",
            "tags": ["documentation", "backend"],
            "priority": "low",
            "comments": 2
          }
        ]
      },
      {
        "id": "done",
        "title": "Done",
        "status": "done",
        "color": "#06D6A0",
        "icon": "done",
        "cards": [
          {
            "id": "task-004",
            "title": "Setup CI/CD pipeline",
            "description": "Configure GitHub Actions workflows",
            "assignee": "Sam Wilson",
            "due_date": "2024-01-30",
            "tags": ["devops", "automation"],
            "priority": "high",
            "comments": 5
          }
        ]
      }
    ],
    "settings": {
      "allow_card_creation": True,
      "allow_card_deletion": True,
      "allow_card_editing": True,
      "show_wip_limits": True,
      "auto_save": True,
      "show_avatars": True
    },
    "actions": {
      "add_card": {
        "type": "form",
        "title": "Add New Task",
        "description": "Create a new task card",
        "form_schema": {
          "title": "Task Details",
          "fields": [
            {
              "name": "title",
              "label": "Title",
              "type": "text",
              "required": True
            },
            {
              "name": "description",
              "label": "Description",
              "type": "textarea"
            },
            {
              "name": "priority",
              "label": "Priority",
              "type": "select",
              "options": ["low", "medium", "high", "critical"]
            },
            {
              "name": "assignee",
              "label": "Assignee",
              "type": "text"
            }
          ]
        },
        "submit_action": {
          "type": "tool",
          "tool_name": "create_kanban_card"
        }
      },
      "edit_card": {
        "type": "form",
        "title": "Edit Task",
        "tool_name": "update_kanban_card"
      },
      "move_card": {
        "type": "tool",
        "title": "Move Card",
        "tool_name": "move_kanban_card"
      }
    },
    "metadata": {
      "project": "AI Chatbot v2",
      "created_by": "system",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-25T14:45:00Z",
      "version": "1.2.0"
    }
  }
}
    
    layouts = { 
        "layouts": [
            kanban_board
        ]
    }
    return layouts

@mcp.tool(title="Form submission")
def add_record(form_data: dict[str, Any],form_name: str, form_id: str) -> dict[str, Any]:

    return { "status": 200,
            "data": { "form_id": form_id,
                     "message": f"{form_name} is successfully submitted!" }}

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
        Mount("/multiLayout", mcp.streamable_http_app())
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
@click.option("--ngrok", is_flag=True, help="Force ngrok even outside Colab")
def startServer(host, port, ngrok):
    public_url = None
    if ngrok:
        public_url = setup_ngrok(port)

    if public_url:
        print(f"🌍 Public URL: {public_url}")
    else:
        print(f"🚀 Running locally at: http://{host}:{port}")
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
    