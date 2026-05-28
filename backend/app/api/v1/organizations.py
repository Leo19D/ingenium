"""Organizations API endpoints.

TODO: implement CRUD + domain operations.
See docs/04-architecture.md for endpoint layout.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_organizations() -> dict:
    return {"message": "TODO: implement", "resource": "organizations"}
