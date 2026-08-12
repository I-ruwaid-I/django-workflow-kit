from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workflow_kit", "0006_workflowexecution_workflow_ki_current_087898_idx_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="workflowexecution",
            options={
                "ordering": ["-started_at"],
                "permissions": [
                    ("view_analytics", "Can view workflow analytics"),
                ],
            },
        ),
    ]
