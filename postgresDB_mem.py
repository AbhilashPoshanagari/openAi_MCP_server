from datetime import datetime
import json
import logging
from typing import Optional
import config
from bson import ObjectId
from mcp.server.streamable_http import EventId, StreamId, EventStore, EventCallback, EventMessage

from mcp.types import JSONRPCMessage
logger = logging.getLogger(__name__)
from postgres_conn import PostgreSQL

class PostgresEventStore(EventStore):
    def __init__(self):
        self.db = PostgreSQL(
                host=config.POSTGRE_SERVER,
                port=config.POSTGRE_PORT,
                user=config.POSTGRE_USERNAME,
                password=config.POSTGRE_PASSWORD,
                database=config.POSTGRE_DB
            )
        
    async def _ensure_connection(self):
        if self.db is not None:
            query = """
            CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY, 
                    stream_id TEXT,
                    event_id TEXT,
                    message JSONB,              
                    timestamp TIMESTAMPTZ, 
                    message_type TEXT
                );
            """
            self.db.create_update_insert(query)
            vector_ext = """
                CREATE EXTENSION IF NOT EXISTS vector;
            """
            self.db.create_update_insert(vector_ext)

    async def store_event(
        self,
        stream_id: StreamId,
        message: JSONRPCMessage
    ) -> EventId:
        """Store an event into Postgresql."""
        await self._ensure_connection()

        # Generate a unique event ID
        event_id = str(ObjectId())

        # Serialize JSONRPCMessage
        message_dict = message.model_dump(by_alias=True, exclude_none=True)
        message_json = json.dumps(message_dict)
        # print(f"message : {message_json}")
        # Create event document
        insertQuery = """INSERT INTO events (stream_id, event_id, message, timestamp, message_type) VALUES
            (%s, %s, %s::jsonb, %s, %s);
            """
        event_doc = (stream_id, event_id, message_json, datetime.utcnow(), message.root.__class__.__name__)

        # Insert into Postgresql
        self.db.create_update_insert(insertQuery, event_doc)
        # print("Event Id : ", event_id)
        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replay events after the specified event ID."""
        await self._ensure_connection()

        findLastEvent = """
                        SELECT * FROM events WHERE event_id = %s;
                        """
        last_event = self.db.fetch_one(findLastEvent, (last_event_id,))
        # print(f"Last event : {last_event}")

        if not last_event:
            return None

        query = """
                SELECT * FROM events WHERE stream_id = %s AND timestamp > %s ORDER BY timestamp ASC;
                """
        # Query events in chronological order
        events = self.db.fetch_all(query, (last_event["stream_id"], last_event["timestamp"]))
        stream_id = None
        for event_doc in events:
            # Reconstruct JSONRPCMessage
            message_dict = event_doc["message"]
            message = JSONRPCMessage.model_validate(message_dict)

            # Send event
            event_message = EventMessage(message, event_doc["event_id"])
            # print(f"call back : {event_message}")
            await send_callback(event_message)

            # Record stream_id
            if stream_id is None:
                stream_id = event_doc["stream_id"]

        return stream_id

    async def close(self):
        """Close MongoDB connection."""
        if self.db:
            self.db.close()
        