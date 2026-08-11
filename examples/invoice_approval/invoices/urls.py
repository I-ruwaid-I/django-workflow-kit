from django.urls import path

from . import views

app_name = "invoices"

urlpatterns = [
    path("", views.invoice_list, name="invoice_list"),
    path("create/", views.invoice_create, name="invoice_create"),
    path("<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("<int:pk>/submit/", views.invoice_submit, name="invoice_submit"),
    path("<int:pk>/approve/", views.invoice_approve, name="invoice_approve"),
    path("<int:pk>/reject/", views.invoice_reject, name="invoice_reject"),
    path("<int:pk>/comment/", views.invoice_comment, name="invoice_comment"),
    path("<int:pk>/attach/", views.invoice_attach, name="invoice_attach"),
]
