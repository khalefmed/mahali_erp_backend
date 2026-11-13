"""Private files: validated on upload, downloaded only through short-lived signed links."""

from django.conf import settings
from django.core import signing
from django.urls import reverse

from apps.core.exceptions import ApiError

ALLOWED_TYPES = {
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
    b"%PDF-": ("application/pdf", ".pdf"),
    b"RIFF": ("image/webp", ".webp"),
}
SALT = "mahali.private-file"


def sniff(upload) -> tuple[str, str]:
    """Type from the file's first bytes — never trust the client's Content-Type."""
    if upload.size > settings.MAX_DOCUMENT_SIZE:
        raise ApiError("file_too_large", "File is larger than 8 MB.")
    head = upload.read(16)
    upload.seek(0)
    for magic, (content_type, ext) in ALLOWED_TYPES.items():
        if head.startswith(magic) and (magic != b"RIFF" or head[8:12] == b"WEBP"):
            return content_type, ext
    raise ApiError("unsupported_file_type", "Only JPEG, PNG, WebP and PDF are accepted.")


def signed_url(request, kind: str, object_id) -> str:
    token = signing.dumps({"k": kind, "id": str(object_id), "u": str(request.user.pk)}, salt=SALT)
    return request.build_absolute_uri(reverse("private-file", args=[token]))


def unsign(token: str) -> dict:
    return signing.loads(token, salt=SALT, max_age=settings.SIGNED_URL_TTL)
