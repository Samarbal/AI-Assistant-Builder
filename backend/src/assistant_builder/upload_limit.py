from starlette.responses import JSONResponse


class UploadBodyLimit:
    """Bound total multipart bytes, including chunked bodies, before spooling."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or not scope['path'].rstrip('/').endswith('/knowledge-files'):
            return await self.app(scope, receive, send)
        limit = 10_000_000 + 65_536
        received = 0
        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > limit:
                from fastapi import HTTPException
                raise HTTPException(413, 'Upload body exceeds the allowed size')
            return message
        headers = dict(scope['headers'])
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await JSONResponse({'detail': 'Invalid content length'}, 400)(scope, receive, send)
        if declared > limit:
            return await JSONResponse({'detail': 'Upload body exceeds the allowed size'}, 413)(scope, receive, send)
        await self.app(scope, limited_receive, send)
