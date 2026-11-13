from rest_framework.throttling import SimpleRateThrottle


class AuthIpThrottle(SimpleRateThrottle):
    scope = "auth_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class _EmailThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        email = (
            str(request.data.get("email", "")).strip().lower() if hasattr(request, "data") else ""
        )
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": email}


class AuthEmailThrottle(_EmailThrottle):
    scope = "auth_email"


class EmailCodeThrottle(_EmailThrottle):
    scope = "email_code"
