"""Default pagination for the workflow REST API.

List responses are paginated out of the box. Page size can be overridden by the
consumer's ``REST_FRAMEWORK`` settings (e.g. ``PAGE_SIZE``) or via the
``page_size`` query parameter.
"""

from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class WorkflowKitPagination(PageNumberPagination):
    """Standard page-number pagination with a sensible default page size."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
