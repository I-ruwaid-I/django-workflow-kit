from django import forms

from .models import Invoice


class InvoiceForm(forms.ModelForm):
    """Form for creating and editing invoices."""

    class Meta:
        model = Invoice
        fields = ["number", "customer_name", "amount", "description"]
