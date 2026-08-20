import asyncio
import json
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.dependencies import get_current_active_user, get_redis
from app.models.user import User
from app.services.queue_service import QueueService

router = APIRouter(prefix="/queue", tags=["Virtual Queue"])
logger = structlog.get_logger()


def get_queue_service(redis=Depends(get_redis)) -> QueueService:
    return QueueService(redis)


@router.post("/join/{showtime_id}", summary="Join virtual queue for showtime")
async def join_queue(
    showtime_id: int,
    current_user: User = Depends(get_current_active_user),
    service: QueueService = Depends(get_queue_service),
):
    """Join the waiting room / virtual queue for a high-concurrency showtime."""
    return await service.join_queue(showtime_id, current_user.id)


@router.get("/status/{showtime_id}", summary="Get current queue rank and status")
async def get_queue_status(
    showtime_id: int,
    current_user: User = Depends(get_current_active_user),
    service: QueueService = Depends(get_queue_service),
):
    """Poll queue rank, total waiting, and estimated wait time."""
    return await service.get_queue_status(showtime_id, current_user.id)


@router.get("/stream/{showtime_id}", summary="SSE Stream for real-time queue rank updates")
async def stream_queue_status(
    showtime_id: int,
    current_user: User = Depends(get_current_active_user),
    service: QueueService = Depends(get_queue_service),
):
    """
    Server-Sent Events (SSE) endpoint:
    Pushes real-time position updates to client until turn arrives and pass_token is issued.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                status_data = await service.get_queue_status(showtime_id, current_user.id)
                json_str = json.dumps(status_data, ensure_ascii=False)
                yield f"data: {json_str}\n\n"

                if not status_data.get("in_queue") and status_data.get("pass_token"):
                    # Turn arrived and token issued — break stream
                    break

                await asyncio.sleep(2)
        except asyncio.CancelledError:
            logger.info("SSE queue stream cancelled by client", showtime_id=showtime_id, user_id=current_user.id)
        except Exception as e:
            logger.warning("SSE queue stream error", showtime_id=showtime_id, user_id=current_user.id, error=str(e))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/leave/{showtime_id}", summary="Leave virtual queue or release booking slot")
async def leave_queue(
    showtime_id: int,
    current_user: User = Depends(get_current_active_user),
    service: QueueService = Depends(get_queue_service),
):
    """Leave the queue or release an active pass token."""
    success = await service.leave_queue(showtime_id, current_user.id)
    return {"success": success, "message": "Successfully left queue"}
