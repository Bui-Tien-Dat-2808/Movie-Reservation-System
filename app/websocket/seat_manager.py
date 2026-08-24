import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class SeatConnectionManager:
    """Manages WebSocket connections per showtime with Redis Pub/Sub multi-worker support."""

    def __init__(self):
        # Maps showtime_id -> set of active WebSockets on THIS worker
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self._redis: aioredis.Redis | None = None
        self._pubsub_task: asyncio.Task | None = None

    async def init_redis(self, redis_client: aioredis.Redis):
        """Called once during FastAPI application startup (lifespan)."""
        self._redis = redis_client
        if self._pubsub_task is None or self._pubsub_task.done():
            self._pubsub_task = asyncio.create_task(self._listen_pubsub())
            logger.info("redis_pubsub_listener_started_for_seats")

    async def _listen_pubsub(self):
        """Background task listening for seat event pattern subscriptions from Redis."""
        if not self._redis:
            return
        try:
            pubsub = self._redis.pubsub()
            await pubsub.psubscribe("seat_events:*")
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                # Extract showtime_id from 'seat_events:{showtime_id}'
                try:
                    showtime_id = int(channel.split(":")[1])
                except (IndexError, ValueError):
                    continue

                payload = message["data"]
                if isinstance(payload, bytes):
                    payload = payload.decode()

                await self._local_broadcast(showtime_id, payload)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("seat_pubsub_listener_error", error=str(e))

    async def connect(self, showtime_id: int, websocket: WebSocket):
        await websocket.accept()
        if showtime_id not in self.active_connections:
            self.active_connections[showtime_id] = set()
        self.active_connections[showtime_id].add(websocket)
        logger.info(
            "websocket_client_connected",
            showtime_id=showtime_id,
            local_clients=len(self.active_connections[showtime_id])
        )

    def disconnect(self, showtime_id: int, websocket: WebSocket):
        if showtime_id in self.active_connections:
            self.active_connections[showtime_id].discard(websocket)
            if not self.active_connections[showtime_id]:
                del self.active_connections[showtime_id]
        logger.info("websocket_client_disconnected", showtime_id=showtime_id)

    async def _local_broadcast(self, showtime_id: int, payload: str):
        """Sends the payload to active WebSockets connected physically to this worker."""
        if showtime_id not in self.active_connections or not self.active_connections[showtime_id]:
            return

        dead_sockets = set()
        for connection in list(self.active_connections[showtime_id]):
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.warning("websocket_send_failed", error=str(e))
                dead_sockets.add(connection)

        # Cleanup dead sockets
        for dead in dead_sockets:
            self.disconnect(showtime_id, dead)

    async def broadcast(self, showtime_id: int, event_type: str, data: dict):
        """Publishes the event to Redis Pub/Sub — ALL workers receive it."""
        payload = json.dumps({"event": event_type, "showtime_id": showtime_id, **data})
        if self._redis:
            await self._redis.publish(f"seat_events:{showtime_id}", payload)
        else:
            await self._local_broadcast(showtime_id, payload)


# Global singleton seat connection manager
seat_connection_manager = SeatConnectionManager()
