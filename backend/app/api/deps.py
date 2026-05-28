"""
Reusable FastAPI dependencies.

`get_current_org_id` — vraća UUID trenutne organizacije.
  Trenutno: hardkodirana demo organizacija iz seed.sql.
  Kada implementiraš auth, samo zamijeni ovu funkciju da čita iz JWT-a.
"""

from __future__ import annotations

from uuid import UUID

# Demo org iz db/seed.sql — sve dok nemamo auth
DEMO_ORG_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000010")


def get_current_org_id() -> UUID:
    """Vraća UUID trenutne organizacije. Bez auth-a — vraća demo org."""
    return DEMO_ORG_ID


def get_current_user_id() -> UUID:
    """Vraća UUID trenutnog korisnika. Bez auth-a — vraća demo usera."""
    return DEMO_USER_ID
