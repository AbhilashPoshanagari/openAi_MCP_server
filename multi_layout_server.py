import json
import re
import sys
import contextlib
import logging
from typing import Any, Dict, List, Optional, Union
import uuid
import mcp.types as types
import anyio
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from api import forms_utils
from auth.starlette_security import JWTAuthBackend
from layoutSchema.api_calls import RestApiHelper
from layoutSchema.form_shema import DynamicFormGenerator, FormConfig, FormData, FormInfo, FormResponse, FormWidget
from layoutSchema.generic_layout import TableFormat, TableLayout
from starlette.routing import Mount, Route, WebSocketRoute
from mcp.server.fastmcp import FastMCP, Context
from layouts.form_layout import generate_form_schema
from layouts.map_layout import MapFeature, MapLayout
from mediaServices.video_streaming import get_webrtc_config
from postgres.postgres_conn import PostgreSQL
from resources.resources import Resources
from prompts.prompt import Prompts
from tools.tools import Tools
from starlette.applications import Starlette
from pydantic import BaseModel, Field
import uvicorn
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from mcp.types import ResourceTemplateReference, Completion
import config
import click
from api.forms import form_routes
from user_auth import get_me, login, logout, refresh_token, update_user_status, register, user_details, websocket_endpoint
from auth.auth_service import auth_service
from api.object_detection import media_routes
from api.voice_to_text_conversion import voice_media_routes

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

## EXECUTION FLOW
1. **FIRST**: Always check if the user request matches any layout tool criteria
2. **SECOND**: If YES → Make a tool call (JSON only)
3. **THIRD**: If NO → Respond naturally to help the user

## AVAILABLE LAYOUT TOOLS & WHEN TO USE THEM
1. **table_layout_tool()**: For structured data presentation (rows/columns)
2. **map_layout_tool()**: For geographical/coordinate-based visualization  
3. **create_dynamic_form()**: For dynamic form generation and data collection
4. **button_layout_tool()**: For actions, navigation, and external links

## CORE PRINCIPLES
- ALWAYS output ONLY valid JSON for tool calls
- NEVER include any text before or after the JSON
- Match exact parameter names and types from tool definitions
- Validate data structures before calling

## TOOL SELECTION GUIDELINES

### Use table_layout_tool() when:
- User mentions: "table", "spreadsheet", "grid", "list of records", "tabular format"
- Data contains structured fields, rows, columns
- Response includes arrays of objects with similar keys

### Use map_layout_tool() when:
- User mentions: "locations", "addresses", "coordinates", "places", "on map", "where is", "near me"
- Data contains latitude/longitude pairs or addresses
- Each GeoJSON Feature must have geometry property

### Use create_dynamic_form() when:
- User wants: "create a form", "fill out", "collect data", "survey", "report", "registration"
- User specifies form fields or asks to generate a form
- IMPORTANT: Do NOT include buttons as form widgets
- Valid widget types only: textBox, textArea, number, email, date, dropdown, select, checkbox, radio, status

### Use button_layout_tool() when:
- User wants: "open", "go to", "navigate", "click here", "link", "action"
- User asks for external links or mobile app deep links

## FINAL REMINDER
- OUTPUT ONLY JSON, NOTHING ELSE
- NO HTML, NO MARKDOWN, NO EXPLANATIONS
"""

# Configure logging
logger = logging.getLogger(__name__)

mcp = FastMCP(name=config.MCP_SERVER_NAME, host = config.MCP_HOST, debug = True,
                port = config.MCP_PORT, json_response=False,
                stateless_http=False, instructions=server_instructions)


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

    Example feature sturcture: [{{
                "type": "Feature",
                "id": "rest_1",
                "properties": {{
                    "name": "Third Wave Coffee",
                    "type": "Cafe",
                    "address": "Knowledge City, Raidurg"
                }},
                "geometry": {{
                    "type": "Point",
                    "coordinates": [78.37385, 17.43352]
                }}
            }}]
    
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
    wms_layers: List[Dict] = None
) -> Dict[str, Any]:
    # print(f"Input features first 200 chars: {repr(features[:200])}")
    try: 
        feature_dicts = [feature.to_dict() for feature in features]

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

        layouts = {
            "layouts": [{
                "type": "map",
                "data": map_data
            }]
        }

        print(f"Map : {layouts}")
        
        return layouts
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "LLM must provide valid map configuration. See examples."
        } 


@mcp.tool(
        title="Create Dynamic Form",
    description="""
            FORM CREATION TOOL FOR LLMs
            ===========================
            This tool allows LLMs to generate dynamic forms by providing form configuration data.

            HOW TO USE THIS TOOL:
            ---------------------
            1. The LLM should call `generate_dynamic_form()` with a properly formatted form configuration
            2. The configuration must follow the schema structure below
            3. The tool returns a structured form layout that can be rendered by a UI
            4. The form layout is having dropdown or select widgetType you must add options form that.

            SCHEMA STRUCTURE LLM MUST FOLLOW:
            ---------------------------------
            {{
                "formInfo": {{
                    "_id": "form_123",
                    "name": "Form Title",
                    "createdBy": "creator_name",
                    "description": "Form description",
                    "version": "1.0"
                }},
                "formWidgets": [
                    {{
                        "_id": "widget_1",
                        "id": "field_1",
                        "label": "Field Label",
                        "type": "textBox",  # Must be one of allowed types
                        "isRequired": true,
                        "placeholder": "Enter text here",
                        "defaultValue": "",
                        "position": 1,
                        "formId": "form_123"
                    }},
                    # ... more widgets
                ],
                "isCurrentVersion": true
            }}

            ALLOWED WIDGET TYPES:
            ---------------------
            - textBox: Single-line text input
            - textArea: Multi-line text input
            - number: Numeric input
            - email: Email input with validation
            - date: Date picker
            - dropdown: Select from dropdown
            - select: Single selection
            - checkbox: Boolean checkbox
            - radio: Radio button group
            - status: Status selector

            EXAMPLE CONFIGURATIONS FOR LLM:
            ------------------------------
            """,
    annotations={
        "formInfo": {
            "type": "dict",
            "description": "Form information will be here."
        },
        "formWidgets": {
            "type": "dict",
            "description": "main form configuration schema."
        },
        "form_title": {
            "type": "string",
            "description": "Optional title override for the form"
        }
    }
)
def create_dynamic_form(
    formInfo: FormInfo,
    formWidgets: List[FormWidget],
    form_title: Optional[str] = None
) -> Dict[str, Any]:
    try:
    
        ALLOWED_TYPES = {
                "textBox", "status", "dropdown", "select",
                "checkbox", "radio", "textArea", "number",
                "date", "email"
            }
        missing_types: set[str] = set()
        valid_widgets = []
        
         # Filter out invalid widget types BEFORE validation
        for widget in formWidgets:
             # If widget is already a Pydantic object
            if isinstance(widget, FormWidget):
                wtype = widget.type
            else:
                # It is still a dict
                wtype = widget.get("type")
            
            if wtype not in ALLOWED_TYPES:
                missing_types.add(str(wtype))
                continue  # Skip invalid widgets

            # Convert dict → Pydantic object
            if isinstance(widget, dict):
                widget = FormWidget(**widget)
                
            valid_widgets.append(widget)

        # apply sanitized widgets back to the structure
        if missing_types:
            comment = (
                "The following widget types were not supported and were removed: "
                + ", ".join(sorted(missing_types))
            )
        else:
            comment = "All widget types recognized successfully."

        # Sort widgets by position
        sorted_widgets = sorted(valid_widgets, key=lambda x: x.position)
        
        # Generate form schema
        form_schema = generate_form_schema(sorted_widgets)

        form_id = formInfo.id or str(uuid.uuid4())
        form_available = forms_utils.get_form_schema(form_id)
        if not form_available:
            form_info={
                    "id": formInfo.id,
                    "name": formInfo.name,
                    "createdBy": formInfo.createdBy,
                    "description": formInfo.description,
                    "version": formInfo.version
                },
            response = forms_utils.insert_form_schema(form_id= form_id, 
                                                        title= form_title or formInfo.name, 
                                                        description=formInfo.description or "", 
                                                        schema_json=form_schema, 
                                                        form_info=form_info, is_active=True)
            print(f"Form creation response: {response}")
        if form_available:
            db_check = form_available["form_id"]
        else:
            db_check = response
        formLayout = { 
                "layouts": [{
                    "type": "form",
                    "data": {
                        "title": form_title or formInfo.name,
                        "schema": form_schema,  # Direct schema for elicitation component
                        "form_info": {
                            "form_id": form_id,
                            "form_name": formInfo.name or "Unknow",
                            "createdBy": formInfo.createdBy,
                            "description": formInfo.description,
                            "version": formInfo.version
                        },
                        "metadata": {
                            "totalFields": len(sorted_widgets),
                            "user_id": "123456",
                            "session_id": "abcdef",
                            "db_check": db_check,
                            "comment": comment
                        },
                        "actions": {
                            "submit": {
                                "type": "api",
                                "title": "Submit",
                                "url": "http://localhost:8100/api/forms/{form_id}/submit",
                                "method": "POST",
                                "auth_strategy": "none",      # "bearer_token", "basic_auth", "api_key", "none"
                                "description": f"Submit {formInfo.name} form",
                                "params": {
                                    "path": {
                                        "form_id": {
                                            "type": "form_info",
                                            "field":"form_id",
                                            "required": True
                                        }
                                    },
                                    "body": {
                                        "submission_data": {
                                            "type": "json",
                                            "required": True
                                            },
                                        "form_info": {
                                            "type": "form_info",
                                            "field": ["form_name", "version", "description", "createdBy"],
                                            "required": True
                                            },
                                        "user_id": {
                                            "type": "metadata",
                                            "field": "user_id",
                                            "required": True
                                            },
                                        "session_id": {
                                            "type": "metadata",
                                            "field": "session_id",
                                            "required": True
                                        }
                                    }
                                },
                                "response_format": {
                                    "success_path": "status",
                                    "success_value": 200,
                                    "message_path": "data.message",
                                    "error_path": "detail.error",
                                    "data_path": "data"
                                },
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
        
        # Prepare response
        return formLayout
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "LLM must provide valid form configuration. See examples."
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
def kanban_testing(Work_title: str):
    """Get all map features in layout format"""
    kanban_board = {
  "type": "kanban",
  "data": {
    "board_title": "Electrical Field Service Tasks",
    "board_id": "electrical-field-001",
    "location": {
      "base_location": "Gachibowli, Hyderabad, Telangana, India",
      "service_radius_km": 25,
      "regions_covered": [
        "Madhapur",
        "Kondapur",
        "Raidurg",
        "Hi-Tech City",
        "Financial District"
      ]
    },
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
            "id": "task-EL-001",
            "title": "Inspect transformer unit at Madhapur",
            "description": "Perform thermal scanning and check load imbalance.",
            "assignee": "Ramesh Kumar",
            "due_date": "2024-03-10",
            "tags": ["maintenance", "transformer", "inspection"],
            "priority": "high",
            "attachments": [
              {
                "name": "transformer_checklist.pdf",
                "url": "/docs/transformer_checklist.pdf",
                "type": "pdf"
              }
            ],
            "comments": 1,
            "metadata": {
              "location": "Madhapur Substation - TS Electric Ltd.",
              "equipment_id": "TR-4521",
              "created_by": "Supervisor",
              "service_type": "Periodic Maintenance"
            }
          },
          {
            "id": "task-EL-002",
            "title": "Install new MCB units",
            "description": "Install and test 4 new MCB units at commercial site.",
            "assignee": "Anil Verma",
            "due_date": "2024-03-12",
            "tags": ["installation", "MCB", "safety"],
            "priority": "medium",
            "comments": 0,
            "metadata": {
              "location": "Hi-Tech City Phase 2",
              "equipment_id": "MCB-7891",
              "created_by": "Admin",
              "service_type": "New Installation"
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
            "id": "task-EL-003",
            "title": "Repair streetlight circuit",
            "description": "Diagnose faulty wiring and replace damaged connectors.",
            "assignee": "Mahesh Patil",
            "due_date": "2024-03-08",
            "tags": ["repair", "wiring", "fieldwork"],
            "priority": "high",
            "comments": 3,
            "metadata": {
              "location": "Raidurg Road – Sector B",
              "equipment_id": "SL-9982",
              "service_type": "Emergency Repair"
            }
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
            "id": "task-EL-004",
            "title": "Load testing for office facility",
            "description": "Conduct load test and prepare stability report.",
            "assignee": "Suresh Naik",
            "due_date": "2024-03-06",
            "tags": ["testing", "load-test", "commercial"],
            "priority": "medium",
            "comments": 2,
            "metadata": {
              "location": "Financial District Tower-5",
              "equipment_id": "LT-2234",
              "service_type": "Testing"
            }
          }
        ]
      },
      {
        "id": "done",
        "title": "Completed",
        "status": "done",
        "color": "#06D6A0",
        "icon": "done",
        "cards": [
          {
            "id": "task-EL-005",
            "title": "Replace faulty capacitor bank",
            "description": "Removed old unit and installed new capacitor bank.",
            "assignee": "Farhan Ahmed",
            "due_date": "2024-02-28",
            "tags": ["replacement", "capacitor-bank", "high-voltage"],
            "priority": "high",
            "comments": 4,
            "metadata": {
              "location": "Kondapur Industrial Zone",
              "equipment_id": "CB-5517",
              "service_type": "Critical Replacement"
            }
          }
        ]
      }
    ],
    "settings": {
      "allow_card_creation": False,
      "allow_card_deletion": False,
      "allow_card_editing": True,
      "show_wip_limits": True,
      "auto_save": True,
      "show_avatars": True
    },
    "actions": {
      "add_card": {
        "type": "form",
        "title": "Add New Field Task",
        "description": "Assign or create a new electrical field service task",
        "form_schema": {
          "title": "Task Details",
          "fields": [
            { "name": "title", "label": "Title", "type": "text", "required": True },
            { "name": "description", "label": "Description", "type": "textarea" },
            {
              "name": "priority",
              "label": "Priority",
              "type": "select",
              "options": ["low", "medium", "high", "critical"]
            },
            { "name": "assignee", "label": "Assignee", "type": "text" },
            { "name": "location", "label": "Location", "type": "text" }
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
      "project": "Field Service Management System",
      "created_by": "system",
      "created_at": "2025-12-01T10:00:00Z",
      "updated_at": "2025-12-05T16:20:00Z",
      "version": "1.0.0"
    }
  }
}

    
    layouts = { 
        "layouts": [
            kanban_board
        ]
    }
    return layouts

@mcp.tool(title="Create Kanban Card")
def create_kanban_card(card_data: dict[str, Any]) -> dict[str, Any]:
    # Here you would add logic to insert the card into your data store
    return {
        "status": "success",
        "message": "Kanban card created successfully",
        "card_data": card_data
    }

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

# Custom authentication error handler
def on_auth_error(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=401)

# Create middleware stack
middleware = [
    Middleware(CORSMiddleware,
        allow_origins=["*"],  # Or specify: ["http://localhost:4200"]
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    ),
    Middleware(AuthenticationMiddleware, 
               backend=JWTAuthBackend(), 
               on_error=on_auth_error)
]

routes = [
    Mount("/multiLayout", mcp.streamable_http_app()),
    Mount("/api/forms", routes=form_routes),
    # Route("/api/health", health_check),
    Route("/api/config", get_webrtc_config),
    Route("/api/auth/register", register, methods=["POST"]),
    Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/refresh", refresh_token, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/auth/me", get_me, methods=["GET"]),
    Route("/api/auth/{username}", user_details, methods=["GET"]),
    # Route("/api/users/online", get_online_users, methods=["GET"]),
    Route("/api/users/status", update_user_status, methods=["POST"]),
    Mount("/api/media", routes=media_routes),
    Mount("/api/voice", routes=voice_media_routes),
    WebSocketRoute("/ws/{room_id}", websocket_endpoint)
]

# Create the Starlette app and mount the MCP servers
app = Starlette(
    routes=routes,
    lifespan=lifespan,
    middleware=middleware
)

# Enable CORS
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # Or specify: ["http://localhost:4200"]
#     allow_methods=["GET", "POST"],
#     allow_headers=["*"],
#     expose_headers=["mcp-session-id"]
# )


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
    