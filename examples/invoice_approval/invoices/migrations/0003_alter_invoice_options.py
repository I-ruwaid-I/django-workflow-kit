from django.db import migrations


class Migration(migrations.Migration):
    """Add the canonical invoice permissions used by the demo workflow."""

    dependencies = [
        ("invoices", "0002_remove_invoice_status"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="invoice",
            options={
                "ordering": ["created_at"],
                "permissions": [
                    ("can_finalize_invoice", "Can finalize an approved invoice"),
                    ("can_reject_invoice", "Can reject an invoice in review"),
                ],
            },
        ),
    ]