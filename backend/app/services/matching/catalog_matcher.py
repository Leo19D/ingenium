"""
Catalog matcher — finds best stock item match for an extracted line item.

Semantičko matchiranje (in-process, bez pgvectora ni ML ovisnosti):
  1. Exact SKU match → score 1.0
  2. Semantic score = kosinus sličnost TF-IDF vektora znakovnih n-grama
     (hvata preraspored riječi i hrvatsku morfologiju: kabel/kabela/kabeli
     dijele n-grame) + domenska normalizacija (sinonimi, mjerne jedinice).
  3. Spec match = poklapanje brojčanih specifikacija (W, K, dimenzije, IP, V) —
     to su pravi diskriminatori u rasvjeti/elektromaterijalu.

Score = 0.6 * cosine + 0.4 * spec_match. Backward-compatibilan interfejs
(MatchCandidate / MatchResult / match_item) — pipeline se ne mijenja.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.stock import StockItem

# Domenski sinonimi (HR/EN) → kanonski oblik. Bez dijakritika (normaliziramo prije).
_SYNONYMS = {
    "svjetiljka": "luminaire", "svetiljka": "luminaire", "lampa": "luminaire",
    "rasvjeta": "luminaire", "svjetlo": "luminaire", "svetlo": "luminaire",
    "zarulja": "bulb", "sijalica": "bulb", "zarulje": "bulb",
    "kabel": "cable", "kabal": "cable", "kablovi": "cable", "vodic": "cable",
    "prekidac": "switch", "sklopka": "switch", "prekidaci": "switch",
    "uticnica": "socket", "uticnice": "socket", "uticnicu": "socket",
    "napajanje": "driver", "drajver": "driver", "transformator": "driver", "napajac": "driver",
    "reflektor": "floodlight", "reflektori": "floodlight",
    "nadgradna": "surface", "nadgradni": "surface",
    "ugradna": "recessed", "ugradni": "recessed",
    "panel": "panel", "paneli": "panel", "ploca": "panel",
    "led": "led", "rasvjetni": "luminaire",
}

_DIA = str.maketrans({"č": "c", "ć": "c", "ž": "z", "š": "s", "đ": "d",
                      "Č": "c", "Ć": "c", "Ž": "z", "Š": "s", "Đ": "d"})

# Mjerne jedinice koje lijepimo uz broj: "40 w" → "40w"
_UNIT_RE = re.compile(r"(\d+)\s*(w|kw|k|v|a|ma|mm|cm|m|lm|ip|deg)\b")
_DIM_RE = re.compile(r"(\d+)\s*[x×*]\s*(\d+)(?:\s*[x×*]\s*(\d+))?")
_NGRAM = 3


@dataclass
class MatchCandidate:
    stock_item_id: UUID
    sku: str
    name: str
    category: str | None
    unit: str
    unit_cost: Decimal | None
    quantity_on_hand: Decimal
    score: float          # 0..1
    match_method: str     # exact_sku | semantic
    explanation: str


@dataclass
class MatchResult:
    description: str
    sku_hint: str | None
    candidates: list[MatchCandidate] = field(default_factory=list)
    accepted: MatchCandidate | None = None   # auto-accepted if score >= 0.92
    needs_review: bool = True


@dataclass
class CatalogIndex:
    """Predizračunati TF-IDF vektori kataloga — gradi se jednom po dokumentu."""
    items: list[StockItem]
    idf: dict[str, float]
    default_idf: float
    vectors: list[dict[str, float]]
    norms: list[float]
    specs: list[dict[str, set]]


# ── Normalizacija + vektorizacija ──────────────────────────────────────────


def _normalize(text: str) -> str:
    s = (text or "").translate(_DIA).lower()
    s = _DIM_RE.sub(lambda m: "x".join(g for g in m.groups() if g), s)  # 600 x 600 → 600x600
    s = _UNIT_RE.sub(r"\1\2", s)                                        # 40 w → 40w
    tokens = re.findall(r"[a-z0-9]+", s)
    return " ".join(_SYNONYMS.get(t, t) for t in tokens)


def _ngrams(normalized: str) -> Counter:
    t = normalized.replace(" ", "_")
    if len(t) < _NGRAM:
        return Counter({t: 1}) if t else Counter()
    return Counter(t[i:i + _NGRAM] for i in range(len(t) - _NGRAM + 1))


def _extract_specs(normalized: str) -> dict[str, set]:
    """Brojčane specifikacije iz normaliziranog teksta (W, K, V, IP, dimenzije)."""
    specs: dict[str, set] = {}
    for m in re.finditer(r"(\d+)(w|kw|k|v|a|lm|ip)\b", normalized):
        specs.setdefault(m.group(2), set()).add(int(m.group(1)))
    for m in re.finditer(r"(\d+)x(\d+)(?:x(\d+))?", normalized):
        dims = tuple(sorted(int(g) for g in m.groups() if g))
        specs.setdefault("dim", set()).add(dims)
    return specs


def _spec_match(q: dict[str, set], c: dict[str, set]) -> float:
    """0..1 — udio podudarnih specifikacija; kazna za prisutan ali drukčiji spec."""
    if not q:
        return 0.5  # query nema specova → neutralno
    score = 0.0
    for key, qvals in q.items():
        cvals = c.get(key)
        if cvals and qvals & cvals:
            score += 1.0
        elif cvals:
            score -= 0.5  # spec postoji ali se razlikuje (npr. 40W vs 60W)
    return max(0.0, score / len(q))


def _cosine(qv: dict[str, float], qnorm: float, iv: dict[str, float], inorm: float) -> float:
    if not qv or not iv or qnorm == 0 or inorm == 0:
        return 0.0
    a, b = (qv, iv) if len(qv) <= len(iv) else (iv, qv)
    dot = sum(w * b.get(g, 0.0) for g, w in a.items())
    return dot / (qnorm * inorm)


async def build_catalog_index(db: AsyncSession, org_id: UUID) -> CatalogIndex:
    """Učitaj stock i predizračunaj TF-IDF vektore (jednom po dokumentu)."""
    stock = list((await db.execute(
        select(StockItem).where(StockItem.org_id == org_id)
    )).scalars().all())

    norm_texts = [_normalize(f"{i.name} {i.sku} {i.category or ''}") for i in stock]
    counters = [_ngrams(t) for t in norm_texts]

    n = max(1, len(stock))
    df: Counter = Counter()
    for c in counters:
        df.update(c.keys())
    idf = {g: math.log((1 + n) / (1 + d)) + 1.0 for g, d in df.items()}
    default_idf = math.log(1 + n) + 1.0

    vectors: list[dict[str, float]] = []
    norms: list[float] = []
    for c in counters:
        v = {g: tf * idf[g] for g, tf in c.items()}
        vectors.append(v)
        norms.append(math.sqrt(sum(x * x for x in v.values())) or 1.0)

    specs = [_extract_specs(_normalize(i.name)) for i in stock]
    return CatalogIndex(stock, idf, default_idf, vectors, norms, specs)


async def match_item(
    *,
    db: AsyncSession,
    org_id: UUID,
    description: str,
    sku_hint: str | None = None,
    top_n: int = 3,
    index: CatalogIndex | None = None,
) -> MatchResult:
    result = MatchResult(description=description, sku_hint=sku_hint)
    idx = index or await build_catalog_index(db, org_id)
    if not idx.items:
        return result

    qnorm_text = _normalize(description)
    qc = _ngrams(qnorm_text)
    qv = {g: tf * idx.idf.get(g, idx.default_idf) for g, tf in qc.items()}
    qnorm = math.sqrt(sum(x * x for x in qv.values())) or 1.0
    qspecs = _extract_specs(qnorm_text)
    hint = (sku_hint or "").strip().lower()

    scored: list[tuple[float, str, int]] = []
    for i, item in enumerate(idx.items):
        if hint and hint == item.sku.lower():
            scored.append((1.0, "exact_sku", i))
            continue
        cosine = _cosine(qv, qnorm, idx.vectors[i], idx.norms[i])
        specscore = _spec_match(qspecs, idx.specs[i])
        combined = min(0.99, 0.6 * cosine + 0.4 * specscore)
        scored.append((combined, "semantic", i))

    scored.sort(key=lambda x: x[0], reverse=True)
    for score, method, i in scored[:top_n]:
        if score < 0.25:
            continue
        item = idx.items[i]
        expl = "Točan SKU" if method == "exact_sku" else f"Semantička sličnost {score:.0%}"
        result.candidates.append(MatchCandidate(
            stock_item_id=item.id,
            sku=item.sku,
            name=item.name,
            category=item.category,
            unit=item.unit,
            unit_cost=item.unit_cost,
            quantity_on_hand=item.quantity_on_hand,
            score=round(score, 3),
            match_method=method,
            explanation=expl,
        ))

    if result.candidates and result.candidates[0].score >= 0.92:
        result.accepted = result.candidates[0]
        result.needs_review = False

    return result


# ── Fallback nabavne cijene iz cjenika dobavljača ───────────────────────────
# Kad artikl NIJE na skladištu, nabavnu cijenu uzimamo iz kataloga: najjeftiniji
# (zadnji važeći) cjenik dobavljača za matchirani proizvod → znamo i kome naručiti.


@dataclass
class SupplierOfferIndex:
    product_ids: list[UUID]
    texts: list[str]            # za exact-sku/normalizaciju
    skus: list[str]
    vectors: list[dict[str, float]]
    norms: list[float]
    idf: dict[str, float]
    default_idf: float
    offers: list[dict | None]   # najbolja ponuda po proizvodu (ili None ako nema cijene)


async def build_supplier_offer_index(db: AsyncSession, org_id: UUID) -> SupplierOfferIndex | None:
    """Index proizvoda iz kataloga + najjeftinija (zadnja važeća) cijena dobavljača."""
    from app.db.models.product import Product, SupplierPriceHistory, SupplierProduct

    products = list((await db.execute(
        select(Product).where(Product.org_id == org_id, Product.is_active.is_(True))
    )).scalars().all())
    if not products:
        return None

    prod_ids = [p.id for p in products]
    rows = (await db.execute(
        select(
            SupplierProduct.id, SupplierProduct.product_id, SupplierProduct.supplier_id,
            SupplierProduct.supplier_name, SupplierPriceHistory.unit_price,
            SupplierPriceHistory.currency, SupplierPriceHistory.valid_from,
            SupplierPriceHistory.id.label("ph_id"),
        )
        .join(SupplierPriceHistory, SupplierPriceHistory.supplier_product_id == SupplierProduct.id)
        .where(SupplierProduct.product_id.in_(prod_ids), SupplierProduct.is_active.is_(True))
    )).all()

    # Zadnja važeća cijena po supplier_productu; tie-break po PK cijene (deterministički
    # kad više cijena dijeli isti valid_from, npr. bulk uvoz cjenika u istom trenutku).
    latest: dict = {}
    for r in rows:
        cur = latest.get(r.id)
        if cur is None or (r.valid_from, r.ph_id) > (cur.valid_from, cur.ph_id):
            latest[r.id] = r
    # Najjeftinija po proizvodu
    best: dict[UUID, dict] = {}
    for r in latest.values():
        off = best.get(r.product_id)
        price = float(r.unit_price)
        if off is None or price < off["unit_cost"]:
            best[r.product_id] = {
                "product_id": str(r.product_id),
                "supplier_product_id": str(r.id),
                "supplier_id": str(r.supplier_id),
                "supplier_name": r.supplier_name,
                "unit_cost": price,
                "currency": r.currency,
            }

    norm_texts = [_normalize(f"{p.name} {p.sku} {p.category or ''}") for p in products]
    counters = [_ngrams(t) for t in norm_texts]
    n = max(1, len(products))
    df: Counter = Counter()
    for c in counters:
        df.update(c.keys())
    idf = {g: math.log((1 + n) / (1 + d)) + 1.0 for g, d in df.items()}
    default_idf = math.log(1 + n) + 1.0
    vectors, norms = [], []
    for c in counters:
        v = {g: tf * idf[g] for g, tf in c.items()}
        vectors.append(v)
        norms.append(math.sqrt(sum(x * x for x in v.values())) or 1.0)

    return SupplierOfferIndex(
        product_ids=[p.id for p in products],
        texts=norm_texts,
        skus=[p.sku.lower() for p in products],
        vectors=vectors, norms=norms, idf=idf, default_idf=default_idf,
        offers=[best.get(p.id) for p in products],
    )


def best_supplier_offer(
    description: str, sku_hint: str | None, index: SupplierOfferIndex, min_score: float = 0.45
) -> dict | None:
    """Najbolja ponuda dobavljača za opis. Vraća offer dict (+match meta) ili None."""
    hint = (sku_hint or "").strip().lower()
    if hint:
        for i, sku in enumerate(index.skus):
            if sku == hint and index.offers[i]:
                return {**index.offers[i], "match_sku": index.skus[i], "match_score": 1.0}

    qc = _ngrams(_normalize(description))
    qv = {g: tf * index.idf.get(g, index.default_idf) for g, tf in qc.items()}
    qnorm = math.sqrt(sum(x * x for x in qv.values())) or 1.0

    best_i, best_score = -1, 0.0
    for i in range(len(index.product_ids)):
        if not index.offers[i]:
            continue
        s = _cosine(qv, qnorm, index.vectors[i], index.norms[i])
        if s > best_score:
            best_i, best_score = i, s
    if best_i >= 0 and best_score >= min_score:
        return {**index.offers[best_i], "match_score": round(best_score, 3)}
    return None
