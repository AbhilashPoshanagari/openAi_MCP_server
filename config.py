import os
from dotenv import load_dotenv
load_dotenv(override=True)  # Only takes effect locally

REMOTE_MONGODB_SERVER = os.getenv("REMOTE_MONGODB_SERVER")
REMOTE_MONGODB_DB = os.getenv("REMOTE_MONGODB_DB")
REMOTE_MONGODB_COLLECTION = os.getenv("REMOTE_MONGODB_COLLECTION")

POSTGRE_SERVER = os.getenv("POSTGRE_SERVER")
POSTGRE_PORT = os.getenv("POSTGRE_PORT")
POSTGRE_DB = os.getenv("POSTGRE_DB")
POSTGRE_USERNAME = os.getenv("POSTGRE_USERNAME")
POSTGRE_PASSWORD = os.getenv("POSTGRE_PASSWORD")

MCP_SERVER_NAME = os.getenv("MCP_SERVER_NAME")
MCP_HOST = os.getenv("MCP_HOST")
MCP_PORT = os.getenv("MCP_PORT")