import uuid

import brotli
from brotli import Compressor
from django.utils.cache import patch_vary_headers
from django.utils.regex_helper import _lazy_re_compile


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.id = request.headers.get(
            "X-Request-ID",
            str(uuid.uuid4()),
        )
        response = self.get_response(request)
        if hasattr(request, "id"):
            del request.id

        return response


re_accepts_brotli = _lazy_re_compile(r"\bbr\b")


class BrotliMiddleware:
    """
    Compress content if the browser allows brotli compression.
    Set the Vary header accordingly, so that caches will base their storage
    on the Accept-Encoding header.
    """

    default_level = 4

    def __init__(self, get_response):
        self.get_response = get_response

    def compress_string(self, content):
        return brotli.compress(content, quality=self.default_level)

    # Like compress_string, but for iterators of strings.
    def compress_sequence(self, sequence):
        """
        Like compress_string, but for iterators of strings.
        """
        yield b""

        compressor = Compressor(quality=self.default_level)
        try:
            # Brotli bindings
            process = compressor.process
        except AttributeError:
            # brotlipy
            process = compressor.compress

        for item in sequence:
            out = process(item)
            if out:
                yield out
        out = compressor.finish()
        if out:
            yield out

    def __call__(self, request):
        response = self.get_response(request)
        # It's not worth attempting to compress really short responses.
        if not response.streaming and len(response.content) < 200:
            return response

        # Avoid gzipping if we've already got a content-encoding.
        if response.has_header("Content-Encoding"):
            return response

        patch_vary_headers(response, ("Accept-Encoding",))

        ae = request.META.get("HTTP_ACCEPT_ENCODING", "")
        if not re_accepts_brotli.search(ae):
            return response

        if response.streaming:
            if response.is_async:
                # pull to lexical scope to capture fixed reference in case
                # streaming_content is set again later.
                orignal_iterator = response.streaming_content

                async def brotli_wrapper():
                    async for chunk in orignal_iterator:
                        yield self.compress_string(chunk)

                response.streaming_content = brotli_wrapper()
            else:
                response.streaming_content = self.compress_sequence(response.streaming_content)
            # Delete the `Content-Length` header for streaming content, because
            # we won't know the compressed size until we stream it.
            del response.headers["Content-Length"]
        else:
            # Return the compressed content only if it's actually shorter.
            compressed_content = self.compress_string(response.content)
            if len(compressed_content) >= len(response.content):
                return response
            response.content = compressed_content
            response.headers["Content-Length"] = str(len(response.content))

        # If there is a strong ETag, make it weak to fulfill the requirements
        # of RFC 9110 Section 8.8.1 while also allowing conditional request
        # matches on ETags.
        etag = response.get("ETag")
        if etag and etag.startswith('"'):
            response.headers["ETag"] = "W/" + etag
        response.headers["Content-Encoding"] = "br"

        return response
