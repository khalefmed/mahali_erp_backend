"""RFC 9457 problem details.

Every error response looks like::

    {"type": "about:blank", "title": "...", "status": 409, "code": "insufficient_stock",
     "detail": "...",
     "errors": [{"field": "lines.0.quantity", "code": "min_value", "detail": "..."}]}

`code` is stable and is what the web app translates; `detail` is for developers only.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response


class ApiError(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "bad_request"
    default_detail = "Bad request."

    def __init__(
        self,
        code: str,
        detail: str | None = None,
        *,
        status_code: int | None = None,
        extra: dict | None = None,
    ):
        super().__init__(detail or code, code)
        self.code = code
        self.extra = extra or {}
        if status_code:
            self.status_code = status_code


class Conflict(ApiError):
    status_code = status.HTTP_409_CONFLICT


class Forbidden(ApiError):
    status_code = status.HTTP_403_FORBIDDEN


def _flatten(detail, prefix=""):
    if isinstance(detail, dict):
        for key, value in detail.items():
            name = key if key != "non_field_errors" else ""
            yield from _flatten(value, f"{prefix}.{name}".strip(".") if name else prefix)
    elif isinstance(detail, list):
        if all(isinstance(item, exceptions.ErrorDetail) for item in detail):
            for item in detail:
                yield {"field": prefix or None, "code": item.code, "detail": str(item)}
        else:
            for index, item in enumerate(detail):
                yield from _flatten(item, f"{prefix}.{index}".strip("."))
    else:
        yield {
            "field": prefix or None,
            "code": getattr(detail, "code", "invalid"),
            "detail": str(detail),
        }


CODES_BY_CLASS = {
    exceptions.NotAuthenticated: "not_authenticated",
    exceptions.AuthenticationFailed: "authentication_failed",
    exceptions.PermissionDenied: "permission_denied",
    exceptions.NotFound: "not_found",
    exceptions.MethodNotAllowed: "method_not_allowed",
    exceptions.Throttled: "too_many_requests",
    exceptions.UnsupportedMediaType: "unsupported_media_type",
    exceptions.ParseError: "parse_error",
}


def problem_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    from rest_framework.views import exception_handler  # avoids a circular import at startup

    response = exception_handler(exc, context)
    if response is None:
        return None

    body = {"type": "about:blank", "status": response.status_code}
    if isinstance(exc, ApiError):
        body.update(
            code=exc.code,
            title=exc.code.replace("_", " ").capitalize(),
            detail=str(exc.detail),
            **exc.extra,
        )
    elif isinstance(exc, exceptions.ValidationError):
        body.update(
            code="validation_error",
            title="Validation error",
            detail="The request contains invalid fields.",
            errors=list(_flatten(exc.detail)),
        )
    else:
        code = next((c for cls, c in CODES_BY_CLASS.items() if isinstance(exc, cls)), "error")
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        # simplejwt puts its own code in the detail dict
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            code = str(exc.detail["code"])
            detail = str(exc.detail.get("detail", detail))
        body.update(code=code, title=code.replace("_", " ").capitalize(), detail=detail)
        if isinstance(exc, exceptions.Throttled) and exc.wait:
            body["retry_after"] = int(exc.wait)

    return Response(
        body,
        status=response.status_code,
        headers=dict(response.items()),
        content_type="application/problem+json",
    )
