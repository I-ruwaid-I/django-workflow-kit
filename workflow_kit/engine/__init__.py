"""Workflow execution engine.

Phase 1 implements the core engine: workflow definitions
(:mod:`workflow_kit.engine.workflow`), the definition registry
(:mod:`workflow_kit.engine.registry`) and ORM-backed execution logic
(:mod:`workflow_kit.engine.execution`). Phase 11 adds the developer-facing
layers built purely on top of definitions: static validation
(:mod:`workflow_kit.engine.validation`), declarative parsing
(:mod:`workflow_kit.engine.parse`), introspection and path enumeration
(:mod:`workflow_kit.engine.introspection`), dry-run simulation
(:mod:`workflow_kit.engine.simulation`) and action diagnostics
(:mod:`workflow_kit.engine.explain`).
"""
