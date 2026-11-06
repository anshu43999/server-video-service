"""Single immutable byte-range responses after the caller's authorization."""
import re
from urllib.parse import quote

from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask


def artifact_response(request, artifact, path, *, acquire, release, chunk_size):
    size, sha = int(artifact['sizeBytes']), str(artifact['sha256']).lower()
    etag = '"' + sha + '"'
    headers = {'ETag': etag, 'Accept-Ranges': 'bytes', 'X-Model-SHA256': sha,
               'Content-Disposition': "attachment; filename*=UTF-8''" +
                   quote(path.name.replace('\r', '').replace('\n', ''), safe='')}
    start, end, status = 0, size - 1, 200
    requested = request.headers.get('range')
    if_range = request.headers.get('if-range')
    # Dates/weak validators are deliberately not accepted for immutable SHA identity.
    if requested and (if_range is None or if_range == etag):
        match = re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})', requested.strip())
        if match and any(match.groups()):
            low, high = match.groups()
            if low:
                start, end = int(low), min(int(high), size - 1) if high else size - 1
            else:
                length = int(high)
                start, end = max(0, size - length), size - 1
                if length == 0:
                    start = size
            if start <= end and start < size:
                status = 206
                headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            else:
                match = None
        if match is None or not any(match.groups()):
            headers.update({'Content-Range': f'bytes */{size}', 'Content-Length': '0'})
            return Response(status_code=416, headers=headers)
    headers['Content-Length'] = str(max(0, end - start + 1))
    acquire(request)
    try:
        handle = path.open('rb')
        handle.seek(start)
    except BaseException:
        release()
        raise
    closed = False

    def close():
        nonlocal closed
        if not closed:
            closed = True
            handle.close()
            release()

    async def body():
        remaining = end - start + 1
        try:
            while remaining > 0:
                chunk = handle.read(min(max(1024, chunk_size), remaining))
                if not chunk:
                    raise OSError('immutable artifact truncated while streaming')
                remaining -= len(chunk)
                yield chunk
        finally:
            close()

    return StreamingResponse(body(), status_code=status, headers=headers,
        media_type=str(artifact.get('contentType') or 'application/octet-stream'), background=BackgroundTask(close))
