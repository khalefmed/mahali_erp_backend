from apps.sales import services as sales_services
from apps.sales.models import PaymentMethod

from .models import SupplierPayment


def record_supplier_payment(request, **data) -> SupplierPayment:
    """Same rule as expenses: a cash payment comes out of my open till."""
    session = sales_services.my_open_session(request.store, request.user)
    if data["method"] == PaymentMethod.CASH:
        session = sales_services.require_session(request.store, request.user, session)
    return SupplierPayment.objects.create(
        store=request.store, cash_session=session, created_by=request.user, **data
    )
