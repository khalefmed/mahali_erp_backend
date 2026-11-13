"""Outgoing messages to users.

Every message goes through `notify()`, which picks the channel. Email is the only
channel for the demo; SMS will be added here later without touching callers.
Templates live in ``templates/notifications/<name>.{subject.txt,txt}``.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import translation

logger = logging.getLogger(__name__)


def notify(
    user_or_email, template: str, context: dict | None = None, language: str | None = None
) -> None:
    email = getattr(user_or_email, "email", user_or_email)
    language = language or getattr(user_or_email, "language", None) or settings.LANGUAGE_CODE
    context = {"web_app_url": settings.WEB_APP_URL, **(context or {})}

    def send():
        with translation.override(language):
            subject = render_to_string(f"notifications/{template}.subject.txt", context).strip()
            body = render_to_string(f"notifications/{template}.txt", context)
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
        except Exception:
            logger.exception("notification failed", extra={"template": template})

    # Never email about something that is then rolled back.
    transaction.on_commit(send)
