"""View tests for the Invoice Approval demo (including the workflow actions)."""

import pytest

from invoices.services import create_invoice

pytestmark = pytest.mark.django_db


def _create_invoice(**overrides):
    data = {"number": "INV-V1", "customer_name": "Acme", "amount": "500.00"}
    data.update(overrides)
    return create_invoice(**data)


def test_invoice_list_empty(client):
    response = client.get("/invoices/")
    assert response.status_code == 200
    assert b"No invoices yet" in response.content


def test_invoice_list_shows_invoices(client):
    _create_invoice(number="INV-10")
    response = client.get("/invoices/")
    assert response.status_code == 200
    assert b"INV-10" in response.content


def test_invoice_create_get(client):
    response = client.get("/invoices/create/")
    assert response.status_code == 200
    assert b"Create invoice" in response.content


def test_invoice_create_post(client):
    response = client.post(
        "/invoices/create/",
        {
            "number": "INV-11",
            "customer_name": "Acme",
            "amount": "500.00",
            "description": "Monthly services",
        },
    )
    assert response.status_code == 302
    assert response.url.startswith("/invoices/1/")


def test_invoice_detail(employee_client):
    invoice = _create_invoice(number="INV-12")
    response = employee_client.get(f"/invoices/{invoice.pk}/")
    assert response.status_code == 200
    assert b"INV-12" in response.content
    assert b"Acme" in response.content
    assert b"Draft" in response.content


def test_invoice_detail_unknown_returns_404(employee_client):
    response = employee_client.get("/invoices/9999/")
    assert response.status_code == 404


def test_detail_redirects_anonymous_to_login(client):
    invoice = _create_invoice(number="INV-GUEST")
    response = client.get(f"/invoices/{invoice.pk}/")
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


def test_actions_redirect_anonymous_to_login(client):
    invoice = _create_invoice(number="INV-ACT")
    response = client.post(f"/invoices/{invoice.pk}/submit/")
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


def test_login_with_seeded_credentials(client, demo_users):
    response = client.post(
        "/accounts/login/",
        {"username": "employee", "password": "demo-password-123"},
    )
    assert response.status_code == 302
    assert response.url == "/invoices/"


def test_login_rejects_bad_credentials(client):
    response = client.post(
        "/accounts/login/",
        {"username": "employee", "password": "wrong-password"},
    )
    assert response.status_code == 200
    assert b"employee" in response.content or b"password" in response.content.lower()


def test_logout_returns_login_page(client, demo_users):
    client.force_login(demo_users["employee"])
    response = client.post("/accounts/logout/")
    assert response.status_code == 302
    assert response.url == "/accounts/login/"


def test_submit_action_via_http(employee_client):
    invoice = _create_invoice(number="INV-SUB")
    response = employee_client.post(f"/invoices/{invoice.pk}/submit/")
    assert response.status_code == 302
    invoice.refresh_from_db()
    assert invoice.current_state == "manager_review"


def test_invalid_action_via_http_redirects_with_error(manager_client):
    invoice = _create_invoice(number="INV-ERR")
    response = manager_client.post(f"/invoices/{invoice.pk}/approve/")
    assert response.status_code == 302
    invoice.refresh_from_db()
    assert invoice.current_state == "draft"
    response = manager_client.get(response.url)
    assert b"error" in response.content.lower() or b"cannot" in response.content.lower()


def test_action_get_redirects(employee_client):
    invoice = _create_invoice(number="INV-GET")
    response = employee_client.get(f"/invoices/{invoice.pk}/submit/")
    assert response.status_code == 302
    invoice.refresh_from_db()
    assert invoice.current_state == "draft"


def test_unauthorized_user_cannot_submit(client, demo_users):
    invoice = _create_invoice(number="INV-DENY")
    response = client.post(f"/invoices/{invoice.pk}/submit/")
    assert response.status_code == 302
    invoice.refresh_from_db()
    assert invoice.current_state == "draft"

    client.force_login(demo_users["finance"])
    response = client.post(f"/invoices/{invoice.pk}/submit/")
    assert response.status_code == 302
    invoice.refresh_from_db()
    assert invoice.current_state == "draft"


def test_detail_shows_comments(employee_client):
    invoice = _create_invoice(number="INV-COM")
    invoice.execution.add_comment(user=None, text="Please attach the quotation.")
    response = employee_client.get(f"/invoices/{invoice.pk}/")
    assert response.status_code == 200
    assert b"Please attach the quotation." in response.content
    assert b"Comments" in response.content


def test_add_comment_via_http(employee_client, demo_users):
    invoice = _create_invoice(number="INV-ADD-CO")
    response = employee_client.post(
        f"/invoices/{invoice.pk}/comment/",
        {"text": "Sent to finance for review"},
    )
    assert response.status_code == 302
    comment = invoice.execution.comments.get()
    assert comment.text == "Sent to finance for review"
    assert comment.user == demo_users["employee"]


def test_add_comment_rejects_empty(employee_client):
    invoice = _create_invoice(number="INV-EMPTY-CO")
    response = employee_client.post(
        f"/invoices/{invoice.pk}/comment/",
        {"text": "   "},
    )
    assert response.status_code == 302
    assert invoice.execution.comments.count() == 0


def test_detail_shows_attachments(employee_client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    invoice = _create_invoice(number="INV-ATT")
    invoice.execution.add_attachment(upload=SimpleUploadedFile("receipt.pdf", b"pdf"), user=None)
    response = employee_client.get(f"/invoices/{invoice.pk}/")
    assert response.status_code == 200
    assert b"receipt.pdf" in response.content
    assert b"Attachments" in response.content


def test_upload_attachment_via_http(employee_client, demo_users):
    from django.core.files.uploadedfile import SimpleUploadedFile

    invoice = _create_invoice(number="INV-UP")
    response = employee_client.post(
        f"/invoices/{invoice.pk}/attach/",
        {"file": SimpleUploadedFile("quote.pdf", b"quote-content")},
    )
    assert response.status_code == 302
    attachment = invoice.execution.attachments.get()
    assert attachment.name == "quote.pdf"
    assert attachment.uploaded_by == demo_users["employee"]


def test_upload_attachment_requires_file(employee_client):
    invoice = _create_invoice(number="INV-NOFILE")
    response = employee_client.post(
        f"/invoices/{invoice.pk}/attach/",
        {},
    )
    assert response.status_code == 302
    assert invoice.execution.attachments.count() == 0
