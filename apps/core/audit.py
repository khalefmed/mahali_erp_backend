from .models import AuditEvent


def record(
    request,
    action: str,
    *,
    target=None,
    store=None,
    reason: str = "",
    realm: str | None = None,
    **metadata,
) -> AuditEvent:
    user = getattr(request, "user", None) if request else None
    return AuditEvent.objects.create(
        actor=user if user and user.is_authenticated else None,
        realm=realm or getattr(request, "auth_realm", None) or "system",
        action=action,
        target_type=target.__class__.__name__.lower() if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        store=store,
        reason=reason,
        metadata=metadata,
        ip_address=getattr(request, "client_ip", None) if request else None,
    )
