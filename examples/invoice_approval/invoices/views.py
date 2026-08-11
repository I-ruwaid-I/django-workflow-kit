from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from workflow_kit import WorkflowError

from . import services
from .forms import InvoiceForm
from .models import Invoice

_PAST_LABELS = {
    "submit": "Submitted",
    "approve": "Approved",
    "reject": "Rejected",
}


def invoice_list(request):
    """List all invoices, newest first."""
    invoices = Invoice.objects.order_by("-created_at")
    return render(
        request,
        "invoices/invoice_list.html",
        {"invoices": invoices},
    )


def invoice_create(request):
    """Create a new invoice and start its workflow."""
    if request.method == "POST":
        form = InvoiceForm(request.POST)
        if form.is_valid():
            invoice = services.create_invoice(**form.cleaned_data)
            return redirect("invoices:invoice_detail", pk=invoice.pk)
    else:
        form = InvoiceForm()
    return render(
        request,
        "invoices/invoice_form.html",
        {"form": form},
    )


@login_required
def invoice_detail(request, pk):
    """Show a single invoice, its state, workflow actions and timeline."""
    invoice = get_object_or_404(Invoice, pk=pk)
    available_actions = [
        {"name": action, "url": reverse(f"invoices:invoice_{action}", args=[pk])}
        for action in invoice.available_actions(request.user)
    ]
    return render(
        request,
        "invoices/invoice_detail.html",
        {
            "invoice": invoice,
            "available_actions": available_actions,
            "timeline": invoice.execution.timeline(),
            "pending_approvals": invoice.execution.pending_approvals(),
            "comments": invoice.execution.comments.select_related("user").order_by(
                "created_at", "id"
            ),
            "attachments": invoice.execution.attachments.select_related("uploaded_by").order_by(
                "created_at", "id"
            ),
        },
    )


def _run_action(request, pk, action: str):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method != "POST":
        return redirect("invoices:invoice_detail", pk=pk)
    handler = {
        "submit": services.submit_invoice,
        "approve": services.approve_invoice,
        "reject": services.reject_invoice,
    }[action]
    try:
        if action == "reject":
            handler(invoice, user=request.user, reason=(request.POST.get("reason") or ""))
        else:
            handler(invoice, user=request.user)
        messages.success(
            request,
            f"{_PAST_LABELS[action]} invoice {invoice.number}.",
        )
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("invoices:invoice_detail", pk=pk)


@login_required
def invoice_submit(request, pk):
    """Submit an invoice for review."""
    return _run_action(request, pk, "submit")


@login_required
def invoice_approve(request, pk):
    """Advance (or complete) the invoice at its current review stage."""
    return _run_action(request, pk, "approve")


@login_required
def invoice_reject(request, pk):
    """Reject the invoice from its current review stage."""
    return _run_action(request, pk, "reject")


@login_required
def invoice_comment(request, pk):
    """Attach a comment to the invoice's workflow execution."""
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == "POST":
        text = (request.POST.get("text") or "").strip()
        if text:
            services.add_invoice_comment(invoice, text=text, user=request.user)
            messages.success(request, "Comment added.")
        else:
            messages.error(request, "Comment text cannot be empty.")
    return redirect("invoices:invoice_detail", pk=pk)


@login_required
def invoice_attach(request, pk):
    """Attach an uploaded file to the invoice's workflow execution."""
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == "POST" and request.FILES.get("file"):
        services.attach_invoice_file(invoice, upload=request.FILES["file"], user=request.user)
        messages.success(request, "Attachment uploaded.")
    else:
        messages.error(request, "Choose a file to attach.")
    return redirect("invoices:invoice_detail", pk=pk)
