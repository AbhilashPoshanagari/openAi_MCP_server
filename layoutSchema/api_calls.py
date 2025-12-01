import config
import requests
from fastapi import HTTPException
import json, ast

class RestApiHelper:
    @staticmethod
    def get_request(url: str, headers: dict = {}) -> dict:
        """
        Makes a GET request to the specified URL with optional headers.
        Raises an HTTPException for any network, HTTP, or parsing errors.
        """
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Raise for 4xx/5xx

            try:
                llm_response = response.json()
            except ValueError as e:  # JSON decoding failed
                print(f"Failed to parse JSON from {url}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Invalid JSON response from external API: {e}"
                )

            # logger.info(f"llm_response: {llm_response}")
            return llm_response

        except requests.HTTPError as e:
            print(f"HTTP error for {url}: {e.response.status_code} {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Error fetching data from external API: {e.response.text}"
            )

        except requests.RequestException as e:
            print(f"Network error for {url}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Network error or request failed: {e}"
            )

        except Exception as e:
            print(f"Unexpected error for {url}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected error: {e}"
            )
        
    @staticmethod
    def post_request(url: str, reqBody: dict,  headers: dict = {} ,  type: str = "data") -> dict:
        # Check if query_results.features array exists and has items
        print(f"LLM API URL: {url}")
        try:
            print(json.dumps(reqBody))
            response = None
            if type == "data":
                response = requests.post(url, data=reqBody, timeout=(15, 300), headers=headers)
            else:
                response = requests.post(url, json=reqBody, timeout=(15, 300), headers=headers)
            print(f"LLM API HTTP status: {response}")
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            return response.json()
        except requests.HTTPError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Error fetching user from external API: {e.response.text}"
            )
        except requests.exceptions.Timeout:
            raise HTTPException(
                status_code=101,
                detail=f"Request to {url} timed out."
            )
        except requests.RequestException as e:
            raise HTTPException(
                status_code=500,
                detail=f"Network error or request failed: {e}"
            )
        
    @staticmethod
    def safe_parse_features(features_str: str):
        # 1. If already a list (rare case), return it
        if isinstance(features_str, list):
            return features_str

        # 2. Try direct JSON parse
        try:
            return json.loads(features_str)
        except:
            pass

        # 3. Try fixing single quotes → double quotes
        try:
            fixed = features_str.replace("'", '"')
            return json.loads(fixed)
        except:
            pass

        # 4. Try Python literal_eval (handles single quotes & dicts)
        try:
            return ast.literal_eval(features_str)
        except:
            pass

        # 5. Try un-escaping and loading again
        try:
            cleaned = features_str.encode('utf-8').decode('unicode_escape')
            return json.loads(cleaned)
        except:
            pass

        # If still failing: raise a clear error
        raise ValueError(f"Invalid features string: {features_str}")


