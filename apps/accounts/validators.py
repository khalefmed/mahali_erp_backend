import hashlib
import logging

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class PwnedPasswordValidator:
    """Refuses passwords found in public breaches (Have I Been Pwned, k-anonymity:
    only the first 5 hex chars of the SHA-1 leave the server). Fails open if the
    service is unreachable."""

    def validate(self, password, user=None):
        if not settings.PWNED_PASSWORDS_CHECK:
            return
        digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            response = requests.get(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                headers={"Add-Padding": "true"},
                timeout=3,
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.warning("pwned passwords check unavailable")
            return
        for line in response.text.splitlines():
            candidate, _, count = line.partition(":")
            if candidate == suffix and int(count or 0) > 0:
                raise ValidationError(
                    "This password appeared in a data breach.", code="password_pwned"
                )

    def get_help_text(self):
        return "Your password must not appear in known data breaches."
