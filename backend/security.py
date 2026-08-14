"""Small dependency-free guards for public auth routes and file uploads."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, UploadFile


class SlidingWindowLimiter:
    def __init__(self):
        self._events=defaultdict(deque)
        self._lock=threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int):
        now=time.monotonic()
        cutoff=now-float(window_seconds)
        with self._lock:
            events=self._events[key]
            while events and events[0]<=cutoff:
                events.popleft()
            if len(events)>=int(limit):
                retry=max(1,int(events[0]+window_seconds-now))
                raise HTTPException(429,f'Bạn thao tác quá nhanh. Vui lòng thử lại sau {retry} giây.')
            events.append(now)

            # Bound bookkeeping for long-running processes with many one-off IPs.
            if len(self._events)>10000:
                stale=[k for k,v in self._events.items() if not v or v[-1]<=cutoff]
                for stale_key in stale[:2000]:
                    self._events.pop(stale_key,None)


rate_limiter=SlidingWindowLimiter()


def client_rate_key(request: Request, bucket: str) -> str:
    # Do not trust X-Forwarded-For here unless the deployment explicitly installs
    # a trusted-proxy middleware. request.client cannot be forged by a browser.
    host=request.client.host if request.client else 'unknown'
    return f'{bucket}:{host}'


def enforce_rate_limit(request: Request, bucket: str, limit: int, window_seconds: int):
    rate_limiter.check(client_rate_key(request,bucket),limit,window_seconds)


async def read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read in chunks and abort as soon as max_bytes is exceeded."""
    data=bytearray()
    chunk_size=1024*1024
    while True:
        chunk=await file.read(chunk_size)
        if not chunk:
            break
        data.extend(chunk)
        if len(data)>int(max_bytes):
            raise HTTPException(413,f'File vượt quá giới hạn {int(max_bytes)//1024//1024} MB.')
    if not data:
        raise HTTPException(400,'File rỗng hoặc không đọc được.')
    return bytes(data)
