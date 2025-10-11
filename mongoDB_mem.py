from datetime import datetime
import logging
from typing import Optional
import os
import config
from bson import ObjectId
from mcp.server.streamable_http import EventId, StreamId, EventStore, EventCallback, EventMessage

from mcp.types import JSONRPCMessage
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
# from pymongo.mongo_client import AsyncMongoClient
logger = logging.getLogger(__name__)

class MongoEventStore(EventStore):
    """
    MongoEventStore provides a MongoDB-based implementation of the EventStore interface for MCP session resumability.
    By implementing the EventStore interface, MCP can support various types of event stores for session persistence.
    To use a different backend, simply implement the EventStore interface accordingly.

    This class handles storing and replaying events for a given stream using MongoDB as the backend.
    It ensures connection management, event serialization, and efficient querying via indexes.
    """
    def __init__(
        self,
        connection_string: str = config.REMOTE_MONGODB_SERVER,
        database_name: str = config.REMOTE_MONGODB_DB,
        collection_name: str = config.REMOTE_MONGODB_COLLECTION
    ):
        self.connection_string = connection_string
        self.database_name = database_name
        self.collection_name = collection_name
        self._client: Optional[AsyncIOMotorClient] = None
        self._collection: Optional[AsyncIOMotorCollection] = None
        self._event_counter = 0

    async def _ensure_connection(self):
        """Ensure MongoDB connection is established."""
        if self._client is None:
            self._client = AsyncIOMotorClient(self.connection_string)
            self._collection = self._client[self.database_name][self.collection_name]

            # Create indexes to optimize query performance
            await self._collection.create_index([
                ("stream_id", 1),
                ("event_id", 1)
            ])
            await self._collection.create_index([
                ("stream_id", 1),
                ("timestamp", 1)
            ])

    async def store_event(
        self,
        stream_id: StreamId,
        message: JSONRPCMessage
    ) -> EventId:
        """Store an event into MongoDB."""
        await self._ensure_connection()

        # Generate a unique event ID
        event_id = str(ObjectId())

        # Serialize JSONRPCMessage
        message_dict = message.model_dump(by_alias=True, exclude_none=True)

        # Create event document
        event_doc = {
            "_id": ObjectId(event_id),
            "stream_id": stream_id,
            "event_id": event_id,
            "message": message_dict,
            "timestamp": datetime.utcnow(),
            "message_type": message.root.__class__.__name__
        }

        # Insert into MongoDB
        await self._collection.insert_one(event_doc)

        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replay events after the specified event ID."""
        await self._ensure_connection()

        # Find the timestamp of the last event
        last_event = await self._collection.find_one(
            {"event_id": last_event_id}
        )

        if last_event:
            # Replay events after this timestamp
            query = {
                "stream_id": last_event["stream_id"],
                "timestamp": {"$gt": last_event["timestamp"]}
            }
        else:
            # If event ID not found, cannot replay
            # Need stream_id to replay from the beginning; return None for now
            return None

        # Query events in chronological order
        cursor = self._collection.find(query).sort("timestamp", 1)

        stream_id = None
        async for event_doc in cursor:
            # Reconstruct JSONRPCMessage
            message_dict = event_doc["message"]
            message = JSONRPCMessage.model_validate(message_dict)

            # Send event
            event_message = EventMessage(message, event_doc["event_id"])
            await send_callback(event_message)

            # Record stream_id
            if stream_id is None:
                stream_id = event_doc["stream_id"]

        return stream_id

    async def close(self):
        """Close MongoDB connection."""
        if self._client:
            self._client.close()