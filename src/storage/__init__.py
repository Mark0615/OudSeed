"""Durable multi-tenant storage for users, workspaces, and connections.

This package is the durable replacement for the in-memory onboarding prototype
state. It uses SQLAlchemy so the same models run on SQLite (local dev / CI) and
PostgreSQL (production / Cloud SQL). See `docs/phase2_storage_design.md`.
"""
