import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.stores.models import Store
from apps.stores.roles import Role
from conftest import PNG, add_member, api, client_for, make_store, make_user

pytestmark = pytest.mark.django_db


def upload(client, store_id, kind, content=PNG, name="doc.png"):
    return client.post(
        f"/api/v1/stores/{store_id}/documents",
        {"kind": kind, "file": SimpleUploadedFile(name, content)},
        format="multipart",
    )


def test_full_onboarding_until_approval(owner_client, owner, staff_client):
    created = owner_client.post(
        "/api/v1/stores",
        {"name": "Galaxy Center", "trade": "telephones", "city": "Nouakchott"},
    )
    assert created.status_code == 201
    store_id = created.data["id"]
    assert created.data["status"] == "draft"

    blocked = owner_client.get(f"/api/v1/stores/{store_id}/products")
    assert blocked.status_code == 403
    assert blocked.data["code"] == "store_not_active"

    early = owner_client.post(f"/api/v1/stores/{store_id}/submit")
    assert early.data["code"] == "documents_missing"
    assert set(early.data["missing"]) == {"id_back", "id_front", "storefront"}

    for kind in ("id_front", "id_back", "storefront"):
        assert upload(owner_client, store_id, kind).status_code == 201
    submitted = owner_client.post(f"/api/v1/stores/{store_id}/submit")
    assert submitted.data["status"] == "pending_approval"

    queue = staff_client.get("/api/v1/console/stores?status=pending_approval")
    assert [s["id"] for s in queue.data["results"]] == [store_id]
    detail = staff_client.get(f"/api/v1/console/stores/{store_id}")
    assert len(detail.data["documents"]) == 3
    approved = staff_client.post(f"/api/v1/console/stores/{store_id}/approve", {})
    assert approved.data["status"] == "active"

    owner.refresh_from_db()
    assert owner.identity_verified_at is not None
    assert owner_client.get(f"/api/v1/stores/{store_id}/products").status_code == 200

    # second store: identity already checked, only the storefront is needed
    second = owner_client.post(
        "/api/v1/stores", {"name": "Galaxy 2", "trade": "telephones", "city": "Nouadhibou"}
    )
    onboarding = owner_client.get(f"/api/v1/stores/{second.data['id']}/onboarding")
    assert onboarding.data["missing_documents"] == ["storefront"]


def test_signed_document_link_works_and_expires_by_signature(owner_client, staff_client):
    store_id = owner_client.post(
        "/api/v1/stores", {"name": "S", "trade": "telephones", "city": "Nouakchott"}
    ).data["id"]
    upload(owner_client, store_id, "storefront")
    url = staff_client.get(f"/api/v1/console/stores/{store_id}").data["documents"][0][
        "download_url"
    ]
    response = staff_client.get(url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert staff_client.get(url[:-3] + "xyz").status_code == 404


def test_upload_rejects_non_image_files(owner_client):
    store_id = owner_client.post(
        "/api/v1/stores", {"name": "S", "trade": "telephones", "city": "Nouakchott"}
    ).data["id"]
    response = upload(owner_client, store_id, "storefront", b"<html>evil</html>", "x.png")
    assert response.data["code"] == "unsupported_file_type"


def test_info_requested_then_rejected(owner, staff_client):
    store = make_store(owner, status="pending_approval")
    asked = staff_client.post(f"/api/v1/console/stores/{store.id}/request-info", {"message": ""})
    assert asked.data["code"] == "message_required"
    asked = staff_client.post(
        f"/api/v1/console/stores/{store.id}/request-info", {"message": "Photo floue"}
    )
    assert asked.data["status"] == "info_requested"
    rejected = staff_client.post(
        f"/api/v1/console/stores/{store.id}/reject", {"message": "Activité non autorisée"}
    )
    assert rejected.data["status"] == "rejected"


def test_store_of_someone_else_does_not_exist(store):
    stranger = client_for(make_user("stranger@example.com"))
    assert stranger.get(api(store, "products")).status_code == 404
    assert stranger.get(f"/api/v1/stores/{store.id}").status_code == 404


def test_invitation_flow(store, owner_client, django_capture_on_commit_callbacks):
    from django.core import mail

    with django_capture_on_commit_callbacks(execute=True):
        sent = owner_client.post(
            api(store, "invitations"), {"email": "Caissier@example.com", "role": "cashier"}
        )
    assert sent.status_code == 201
    token = mail.outbox[-1].body.split("/invitations/")[1].split()[0]

    wrong = client_for(make_user("other@example.com"))
    assert wrong.post(f"/api/v1/invitations/{token}/accept").data["code"] == (
        "invitation_wrong_account"
    )
    cashier = client_for(make_user("caissier@example.com"))
    accepted = cashier.post(f"/api/v1/invitations/{token}/accept")
    assert accepted.data["role"] == "cashier"
    assert "sales.create" in accepted.data["permissions"]
    assert cashier.get("/api/v1/me/stores").data[0]["store"]["id"] == str(store.id)


def test_removed_member_loses_access_immediately(store, owner_client):
    seller = add_member(store, Role.SELLER, "seller@example.com")
    seller_client = client_for(seller)
    assert seller_client.get(api(store, "products")).status_code == 200
    membership_id = owner_client.get(api(store, "members")).data[1]["id"]
    assert owner_client.delete(api(store, f"members/{membership_id}")).status_code == 204
    assert seller_client.get(api(store, "products")).status_code == 404


def test_ownership_transfer(store, owner, owner_client):
    manager = add_member(store, Role.MANAGER, "manager@example.com")
    owner_client.post(f"/api/v1/stores/{store.id}/ownership-transfer", {"to_user_id": manager.id})
    manager_client = client_for(manager)
    transfer_id = manager_client.get("/api/v1/me/ownership-transfers").data[0]["id"]
    manager_client.post(f"/api/v1/me/ownership-transfers/{transfer_id}/accept")
    assert Store.objects.get(pk=store.pk).owner == manager
    roles = {m["user"]["email"]: m["role"] for m in owner_client.get(api(store, "members")).data}
    assert roles == {"owner@example.com": "manager", "manager@example.com": "owner"}
