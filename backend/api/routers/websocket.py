"""
WebSocket endpoint for real-time job updates.

Provides real-time progress updates for extraction jobs.
"""

import asyncio
import json
import logging
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# Store active WebSocket connections by job_id
connections: Dict[str, Set[WebSocket]] = {}


class ConnectionManager:
    """Manage WebSocket connections for job updates."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, job_id: str):
        """Accept connection and add to job's connection set."""
        await websocket.accept()

        if job_id not in self.active_connections:
            self.active_connections[job_id] = set()

        self.active_connections[job_id].add(websocket)
        # Only log at debug level to reduce noise
        logger.debug(f"WebSocket connected for job {job_id} (total: {len(self.active_connections[job_id])})")

    def disconnect(self, websocket: WebSocket, job_id: str):
        """Remove connection from job's connection set."""
        if job_id in self.active_connections:
            self.active_connections[job_id].discard(websocket)

            # Clean up empty sets
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]

        # Only log at debug level
        logger.debug(f"WebSocket disconnected for job {job_id}")

    async def send_to_job(self, job_id: str, message: dict):
        """Send message to all connections for a job."""
        if job_id not in self.active_connections:
            return

        disconnected = set()

        for connection in self.active_connections[job_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.add(connection)

        # Clean up failed connections
        for connection in disconnected:
            self.active_connections[job_id].discard(connection)

    async def broadcast_job_update(self, job_id: str, update_type: str, data: dict):
        """Broadcast a job update to all connected clients."""
        message = {
            "type": update_type,
            "job_id": job_id,
            "payload": data,
        }
        await self.send_to_job(job_id, message)


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws/jobs/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for real-time job updates.

    Connect to receive updates for a specific job:
        ws://localhost:8001/ws/jobs/{job_id}

    Messages sent from server:
        - status_update: Job status changed
        - part_started: Part extraction started
        - part_completed: Part extraction completed
        - job_completed: Job finished
        - error: Error occurred

    Message format:
        {
            "type": "status_update",
            "job_id": "...",
            "payload": {
                "status": "extracting",
                "progress": 0.5,
                "current_step": "Extracting part-2..."
            }
        }
    """
    await manager.connect(websocket, job_id)

    try:
        # Send initial status
        from ..database.engine import SessionLocal
        from ..database import crud

        db = SessionLocal()
        try:
            job = crud.get_job(db, job_id)
            if job:
                await websocket.send_json({
                    "type": "initial_status",
                    "job_id": job_id,
                    "payload": job.to_dict(),
                })
            else:
                await websocket.send_json({
                    "type": "error",
                    "job_id": job_id,
                    "payload": {"message": "Job not found"},
                })
        finally:
            db.close()

        # Keep connection alive and handle messages
        while True:
            try:
                # Wait for client messages (ping/pong, cancel, etc.)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0,
                )

                message = json.loads(data)
                message_type = message.get("type")

                if message_type == "ping":
                    await websocket.send_json({"type": "pong"})

                elif message_type == "cancel":
                    # Handle job cancellation request
                    db = SessionLocal()
                    try:
                        crud.update_job_status(
                            db, job_id,
                            status="cancelled",
                            current_step="Cancelled by user",
                        )
                        await websocket.send_json({
                            "type": "cancelled",
                            "job_id": job_id,
                        })
                    finally:
                        db.close()

                elif message_type == "subscribe":
                    # Already subscribed on connect
                    await websocket.send_json({
                        "type": "subscribed",
                        "job_id": job_id,
                    })

            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
    finally:
        manager.disconnect(websocket, job_id)


# =============================================================================
# Helper functions to broadcast updates from extraction process
# =============================================================================

async def notify_status_update(job_id: str, status: str, progress: float, current_step: str):
    """Notify clients of status update."""
    await manager.broadcast_job_update(
        job_id,
        "status_update",
        {
            "status": status,
            "progress": progress,
            "current_step": current_step,
        },
    )


async def notify_part_started(job_id: str, part_name: str):
    """Notify clients that part extraction started."""
    await manager.broadcast_job_update(
        job_id,
        "part_started",
        {"part_name": part_name},
    )


async def notify_part_completed(
    job_id: str,
    part_name: str,
    status: str,
    confidence: float,
    error: str = None,
):
    """Notify clients that part extraction completed."""
    await manager.broadcast_job_update(
        job_id,
        "part_completed",
        {
            "part_name": part_name,
            "status": status,
            "confidence": confidence,
            "error": error,
        },
    )


async def notify_job_completed(
    job_id: str,
    status: str,
    total_time: float,
    parts_completed: int,
    parts_failed: int,
):
    """Notify clients that job completed."""
    await manager.broadcast_job_update(
        job_id,
        "job_completed",
        {
            "status": status,
            "total_time": total_time,
            "parts_completed": parts_completed,
            "parts_failed": parts_failed,
        },
    )


async def notify_error(job_id: str, error: str, part_name: str = None):
    """Notify clients of error."""
    await manager.broadcast_job_update(
        job_id,
        "error",
        {
            "message": error,
            "part_name": part_name,
        },
    )
