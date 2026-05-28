"""Import all ORM models here so Alembic autogenerate sees them.

Order matters for foreign keys — independent tables first, dependent later.
"""

from app.db.models.organization import Organization  # noqa: F401
from app.db.models.user import Membership, User  # noqa: F401
from app.db.models.client import Client, Contact  # noqa: F401
from app.db.models.supplier import Supplier  # noqa: F401
from app.db.models.product import (  # noqa: F401
    Product,
    SupplierPriceHistory,
    SupplierProduct,
)
from app.db.models.stock import StockItem, StockLocation  # noqa: F401
from app.db.models.fx import FxRate  # noqa: F401
from app.db.models.tax import TaxRule  # noqa: F401
from app.db.models.project import Project  # noqa: F401
from app.db.models.document import Document, DocumentExtraction  # noqa: F401
from app.db.models.quote import Quote, QuoteLineItem, QuoteOutcome  # noqa: F401
from app.db.models.audit import AuditLog  # noqa: F401
