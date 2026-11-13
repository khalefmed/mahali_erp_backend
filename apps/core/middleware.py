import uuid


def client_ip(request) -> str | None:
    # Caddy is the only proxy in front of the app and sets X-Forwarded-For.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR")


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.client_ip = client_ip(request)
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response
