"""Private MP4 attachment; the receipt and bytes commit together. No implicit image sync."""
import asyncio
from hashlib import sha256
import re
import threading
import time
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect
from .database import AlertEventRecord, MobileClipRecord
from .project_auth import require_project_capability, PROJECT_ALERTS_DISPOSE

LIMIT = 16 * 1024 * 1024
_slots = threading.BoundedSemaphore(2)
_check = require_project_capability(PROJECT_ALERTS_DISPOSE)


def silent_avc(data):
    # Walk bounded ISO BMFF boxes, including extended sizes. One AVC video track, no audio.
    def boxes(buf):
        pos = 0
        while pos < len(buf):
            if len(buf) - pos < 8: raise ValueError()
            n = int.from_bytes(buf[pos:pos+4], 'big'); tag = bytes(buf[pos+4:pos+8]); header = 8
            if n == 1:
                n = int.from_bytes(buf[pos+8:pos+16], 'big'); header = 16
            elif n == 0: n = len(buf) - pos
            if not header <= n <= len(buf)-pos: raise ValueError()
            yield tag, buf[pos+header:pos+n]; pos += n
    def one(seq, tag):
        matches = (v for k,v in seq if k == tag)
        v = next(matches, None)
        if v is None or next(matches,None) is not None: raise ValueError()
        return v
    try:
        buf = memoryview(data)
        if bytes(buf[4:8]) != b'ftyp' or len(one(boxes(buf), b'ftyp')) < 8 or not len(one(boxes(buf), b'mdat')): return False
        track = one(boxes(one(boxes(buf), b'moov')), b'trak')
        mdia = one(boxes(track), b'mdia'); handler = one(boxes(mdia), b'hdlr')
        stbl = one(boxes(one(boxes(mdia), b'minf')), b'stbl'); stsd = one(boxes(stbl), b'stsd')
        avc = one(boxes(stsd[8:]), b'avc1')
        config = one(boxes(avc[78:]), b'avcC')
        samples = one(boxes(stbl), b'stsz')
        return (bytes(handler[8:12]) == b'vide' and bytes(stsd[4:8]) == b'\0\0\0\1'
                and len(config) >= 7 and config[0] == 1 and config[5] & 31 != 0
                and len(samples) >= 12 and 0 < int.from_bytes(samples[8:12],'big') <= 120)
    except (ValueError, OverflowError): return False


def create_mobile_clip_router(get_db):
    router = APIRouter(); path = '/aiyoloapi/projects/{project_id}/alerts/{event_id}/local-clip'
    def owner(session, ctx, event):
        row = session.get(AlertEventRecord, (ctx.project_id, event))
        if row is None: raise HTTPException(404, detail={'code':'event_not_found'})
        if (row.payload.get('mobileProducer') or {}).get('accountId') != ctx.principal.account_id:
            raise HTTPException(403, detail={'code':'clip_owner_mismatch'})
    def available(ctx,event):
        db = get_db()
        if not db.enabled: raise HTTPException(503, detail={'code':'clip_store_unavailable'})
        if not inspect(db.engine).has_table('mobile_alert_clips'):
            raise HTTPException(503, detail={'code':'clip_store_unavailable'})
        with db.session() as s: owner(s,ctx,event)
    @router.get(path)
    def capability(project_id: str, event_id: str, ctx=Depends(_check)):
        available(ctx,event_id)
        return {'contract':'local-clip/1','maxBytes':LIMIT}

    def store(ctx,event,digest,body):
        key=(ctx.project_id,event,ctx.principal.account_id,digest)
        def reply(r,created):
            return JSONResponse({'contract':'local-clip/1','projectId':r.project_id,'eventId':event,
                'accountId':r.account_id,'sha256':digest,'receiptId':r.receipt_id,'receivedAtMs':r.received_ms}, status_code=201 if created else 200)
        db=get_db()
        try:
            with db.session() as s:
                owner(s,ctx,event); r=s.get(MobileClipRecord,key)
                if r: return reply(r,False)
                r=MobileClipRecord(project_id=key[0],event_id=event,account_id=key[2],sha256=digest,
                    content=bytes(body),receipt_id=str(uuid4()),received_ms=time.time_ns()//1_000_000)
                s.add(r); s.flush(); return reply(r,True)
        except IntegrityError:
            with db.session() as s:
                owner(s,ctx,event); r=s.get(MobileClipRecord,key)
                if r: return reply(r,False)
                raise

    @router.put(path)
    async def upload(project_id: str,event_id: str,request: Request,ctx=Depends(_check)):
        digest=request.headers.get('X-Clip-SHA256','')
        if request.headers.get('X-Clip-Consent') != 'single-v1' or not re.fullmatch('[0-9a-f]{64}',digest): raise HTTPException(422)
        if request.headers.get('content-type') != 'video/mp4': raise HTTPException(415)
        length=request.headers.get('content-length','')
        if not re.fullmatch('[0-9]{1,9}',length) or not 0 < int(length) <= LIMIT: raise HTTPException(413)
        await asyncio.to_thread(available,ctx,event_id)
        if not _slots.acquire(False): raise HTTPException(429)
        try:
            body=bytearray()
            async def receive_body():
                checked = time.monotonic()
                async for chunk in request.stream():
                    if len(body)+len(chunk)>int(length): raise HTTPException(413)
                    if time.monotonic() - checked >= 0.25:
                        current = await _check(request)
                        if current.principal.account_id != ctx.principal.account_id: raise HTTPException(403)
                        checked = time.monotonic()
                    body.extend(chunk)
            try:
                await asyncio.wait_for(receive_body(), timeout=45)
            except asyncio.TimeoutError:
                raise HTTPException(408)
            except ClientDisconnect:
                raise HTTPException(400, detail={'code':'incomplete_clip'})
            if len(body)!=int(length) or sha256(body).hexdigest()!=digest: raise HTTPException(422)
            if not await asyncio.to_thread(silent_avc,body): raise HTTPException(415)
            current=await _check(request)
            if current.principal.account_id!=ctx.principal.account_id or current.project_id!=ctx.project_id: raise HTTPException(403)
            return await asyncio.to_thread(store,current,event_id,digest,body)
        finally: _slots.release()
    return router
