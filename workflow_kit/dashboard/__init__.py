"""Workflow Dashboard (Phase 13, Part B).

A server-rendered Django dashboard that consumes the existing workflow
engine, analytics and service layers — never a second source of truth.

The dashboard is a plain Django app (templates + static CSS, no frontend
framework) so the core package stays free of mandatory frontend dependencies.
Views are thin: they call the same analytics/service functions the REST API
wraps and let the template render the result.

Permissions:
    * every page requires an authenticated user;
    * aggregate analytics screens require staff or the
      ``workflow_kit.view_analytics`` permission (the same rule as the REST
      analytics endpoints);
    * execution-level pages show the user their pending approvals and the
      executions they can act on — the backend engine remains the source of
      truth for every authorization decision.
"""
