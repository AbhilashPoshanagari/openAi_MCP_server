import requests
from fastapi import HTTPException
import json
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice_agent")

class IBMSpeechToTextHelper:
    @staticmethod
    def post_request(
        url: str, audio_data: any, apikey: str, headers: dict = {}, type: str = "data"
    ) -> dict:
        # Check if query_results.features array exists and has items
        logger.info(f"STT API URL: {url}")
        try:
            response = None
            start = time.time()
            logger.info(f"data request")
            response = requests.post(
                url,
                data=audio_data,
                headers=headers,
                auth=("apikey", apikey),
                verify=False,
                timeout=(10, 90)
            )
            logger.info(f"post_request Elapsed time {time.time() - start:.2f}s for {url}")    
            logger.info(f"STT API HTTP status: {response}")
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            return response.json()
        except requests.HTTPError as e:
            logger.error(f"HTTPError: {e}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Error fetching from external API: {e.response.text}",
            )
        except requests.exceptions.Timeout:
            logger.error(f"STT API Timeout")
            raise HTTPException(status_code=101, detail=f"Request to {url} timed out.")
        except requests.RequestException as e:
            logger.error(f"RequestException: {e}")
            raise HTTPException(
                status_code=500, detail=f"Network error or request failed: {e}"
            )
        except Exception as e:
            logger.error(f"Unknown error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Unknown error: {e}"
            )

    # Format the LLM response to return only necessary fields
    @staticmethod
    def format_STT_response(response: dict) -> dict:
        # Check if query_results.features array exists and has items
        if response.get("error"):
            return {
                "status_code": response["results"]["error"].get("code", 401),
                "error": response["results"]["error"].get("message", "Unknown error"),
            }
        else:
            # If features array is empty or doesn't exist, return None
            return {
                "status_code": 200,
                "transcript": response.get("results")[0].get("alternatives", [])[0].get("transcript", "") if response.get("results") else "",
            }
