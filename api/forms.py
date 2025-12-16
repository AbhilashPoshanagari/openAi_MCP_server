
from datetime import datetime
from typing import List, Optional
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
import json
from api import forms_utils
import config
from postgres.postgres_conn import PostgreSQL
from starlette.routing import Route

async def insert_form_schema(request: Request) -> Optional[dict]:
        """Insert a new form schema"""
        try:
            data = await request.json()
            print(f"Received form schema data: {data}")
            form_id = data.get("form_id")
            title = data.get("title")
            description = data.get("description", "")
            schema_json = data.get("schema_json")
            form_info = data.get("form_info", {})
            is_active = data.get("is_active", True)
            response = forms_utils.insert_form_schema(form_id, title, description, schema_json, form_info, is_active)
            return JSONResponse(content={"message": "Form schema inserted successfully", 
                                         "form_id": form_id}, 
                                        status_code=200)
        except Exception as e:
            print(f"Error: {str(e)}")
            raise HTTPException(
                status_code=500, detail={"error": str(e)}
            )
    
async def get_form_schema(request: Request) -> Optional[dict]:
        """Get form schema by form_id"""
        try:
            form_id = request.path_params['form_id']
            response = forms_utils.get_form_schema(form_id)
            print(f"Form submission response: {response}")
            return JSONResponse(content={"data": response}, 
                                status_code=200)
        except Exception as e:
            print(f"Error: {str(e)}")
            raise HTTPException(
                status_code=500, detail={"error": str(e)}
            )

async def insert_form_submission(request) -> Optional[dict]:
    """Insert a form submission"""
    data = await request.json()
    form_id = request.path_params["form_id"]
    submission_data = data.get("submission_data")
    user_id = data.get("user_id")
    form_info = data.get("form_info", {})
    session_id = data.get("session_id", None)
    try:
        submission_data = json.dumps(submission_data)
        response = forms_utils.insert_form_submission(form_id, submission_data, form_info, user_id, session_id)
        print(f"Form submission response: {response}")
        return JSONResponse(content={
                                    "data": {
                                        "message": "Form submitted successfully", 
                                        "form_id": response
                                        }
                                    }, 
                                    status_code=200)
    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(
            status_code=500, detail={"error": str(e)}
        )


async def get_form_submissions(request) -> List[dict]:
    """Get submissions for a specific form"""
    print(f"Received request to get form submissions: {str(request.path_params)}")
    form_id = request.path_params["form_id"]
    limit = request.path_params.get("limit", 10)
    offset = request.path_params.get("offset", 0)
    try:
        response = forms_utils.get_form_submissions(form_id, limit, offset)
        print(f"Form submission response: {response}")
        return JSONResponse(content={"data": response}, 
                            status_code=200)
           
    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(
            status_code=500, detail={"error": str(e)}
        )
    
form_routes = [
    Route('/', insert_form_schema, methods=['POST']),
    Route('/{form_id}', get_form_schema, methods=['GET']),
    Route('/{form_id}/submit', insert_form_submission, methods=['POST']),
    Route('/{form_id}/submissions/{limit}/{offset}', get_form_submissions, methods=['GET'])
]
