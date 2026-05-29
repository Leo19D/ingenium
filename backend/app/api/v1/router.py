"""Top-level v1 API router. Aggregates all sub-routers."""

from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    auth,
    clients,
    documents,
    health,
    organizations,
    products,
    projects,
    quotes,
    stock,
    suppliers,
)

api_router = APIRouter()

# Real implementations
api_router.include_router(health.router, tags=["health"])
api_router.include_router(clients.router, prefix="/clients", tags=["clients"])
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["suppliers"])
api_router.include_router(stock.router, prefix="/stock-items", tags=["stock"])

# TODO stubovi (zasebne PR-ovi)
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(quotes.router, prefix="/quotes", tags=["quotes"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
