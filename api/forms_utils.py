from datetime import datetime
import json
from typing import Any, List, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

import config
from postgres.postgres_conn import PostgreSQL

database_instance = PostgreSQL(
        host=config.POSTGRE_SERVER,
        port=config.POSTGRE_PORT,
        user=config.POSTGRE_USERNAME,
        password=config.POSTGRE_PASSWORD,
        database=config.POSTGRE_DB
    )

def insert_form_schema(form_id: str, title: str, 
                             description: str, 
                             schema_json: str, 
                             form_info: dict[str, Any]= {},
                             is_active: bool = True) -> Optional[dict]:
        """Insert a new form schema"""
        query = """
        INSERT INTO form_schemas (form_id, title, description, schema_json, form_info, is_active)
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
        RETURNING *
        """
        try:
            response = database_instance.create_update_insert(query, 
                                                              (form_id, title, description, 
                                                               json.dumps(schema_json), json.dumps(form_info), is_active))
            return f"New form created with form id : {form_id}"
        except Exception as e:
            print(f"Error: {str(e)}")
            raise str(e)
    
def get_form_schema(form_id: str) -> Optional[dict] | None:
        """Get form schema by form_id"""
        query = """
        SELECT * FROM form_schemas 
        WHERE form_id = %s AND is_active = TRUE
        """
        response = database_instance.fetch_one(query, (form_id,))
        print(f"Form submission response: {response}")
                # Convert the RealDictRow to a regular dictionary
        if response:
            # Method 1: Use dict() and handle serialization
            response_dict = dict(response)
            
            # Convert datetime objects to strings
            for key, value in response_dict.items():
                if isinstance(value, datetime):
                    response_dict[key] = value.isoformat()
            
            return response_dict
        else:
            return None

def insert_form_submission(form_id: str, submission_data: dict[str, Any], form_info: dict[str, Any], user_id: str, session_id: str) -> str | None:
    """Insert a form submission"""
    query = """
    INSERT INTO form_submissions (form_id, submission_data, form_info, user_id, session_id)
    VALUES (%s, %s::jsonb, %s::jsonb, %s, %s)
    RETURNING id, submitted_at
    """
    submission_data = json.dumps(submission_data)
    response = database_instance.create_update_insert(query, (form_id, json.dumps(submission_data), json.dumps(form_info), user_id, session_id))
    print(f"Form submission response: {response}")
    return form_id


def get_form_submissions(form_id: str, limit: int, offset: int) -> List[dict] | None:
    """Get submissions for a specific form"""
    query = """
    SELECT * FROM form_submissions 
    WHERE form_id = %s 
    ORDER BY submitted_at DESC
    LIMIT %s OFFSET %s
    """
    print(f"Executing query: {query} with params: {(form_id, limit, offset)}")
    response = database_instance.fetch_all(query, (form_id, limit, offset))
    print(f"Form submission response: {response}")
    if response:
        # Method 1: Use dict() and handle serialization
        response_dict = [dict(res) for res in response]
        
        # Convert datetime objects to strings
        for res_dict in response_dict:
            for key, value in res_dict.items():
                if isinstance(value, datetime):
                    res_dict[key] = value.isoformat()
        
        return response_dict
    else:
        return None