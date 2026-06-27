"""SSE endpoint for real-time event streaming."""
from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from core.events import EventType

router = APIRouter()


@router.get("/events")
async def stream_events(request: Request):
    """Server-Sent Events endpoint with proper cleanup on disconnect."""
    bus = request.app.state.bus
    queue = asyncio.Queue()

    def _on_event(event):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    # Subscribe to all event types, keep IDs for cleanup
    sub_ids: list[tuple[EventType, int]] = []
    for event_type in EventType:
        sid = bus.subscribe(event_type, _on_event)
        sub_ids.append((event_type, sid))

    recent_events = bus.recent(20)

    async def event_generator():
        try:
            for event in recent_events:
                yield f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            # 客户端断开 → 取消订阅, 防止内存泄漏
            for et, sid in sub_ids:
                try:
                    bus.unsubscribe(et, sid)
                except Exception:
                    pass
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )