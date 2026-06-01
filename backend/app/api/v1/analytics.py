"""Analytics — win rate, margin stats, AI suggestions based on historical data."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_org_id
from app.db.models.client import Client
from app.db.models.quote import Quote, QuoteOutcome
from app.db.session import get_db

router = APIRouter()


class DashboardStats(BaseModel):
    total_quotes: int
    won: int
    lost: int
    open: int
    win_rate_pct: float
    avg_margin_won_pct: float | None
    avg_margin_lost_pct: float | None
    pipeline_value: float
    won_value: float


class MarginSuggestion(BaseModel):
    suggested_min: float
    suggested_max: float
    suggested_target: float
    based_on_quotes: int
    confidence: str  # low / medium / high
    insight: str


@router.get("/overview", response_model=DashboardStats)
async def dashboard_overview(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> DashboardStats:
    """Statistike za dashboard — win rate, marže, pipeline."""

    # Sve ponude s outcomima
    quotes_result = await db.execute(
        select(Quote.id, Quote.status, Quote.total, Quote.margin_pct)
        .where(Quote.org_id == org_id)
    )
    all_quotes = quotes_result.all()
    total = len(all_quotes)

    outcomes_result = await db.execute(
        select(QuoteOutcome.quote_id, QuoteOutcome.outcome)
        .join(Quote, Quote.id == QuoteOutcome.quote_id)
        .where(Quote.org_id == org_id)
    )
    outcomes = {row.quote_id: row.outcome for row in outcomes_result}

    won_quotes  = [q for q in all_quotes if outcomes.get(q.id) == "won"]
    lost_quotes = [q for q in all_quotes if outcomes.get(q.id) == "lost"]
    open_quotes = [q for q in all_quotes if q.id not in outcomes and q.status == "draft"]

    win_rate = (len(won_quotes) / len([q for q in all_quotes if q.id in outcomes]) * 100) if outcomes else 0.0

    def avg_margin(qs: list) -> float | None:
        vals = [float(q.margin_pct) for q in qs if q.margin_pct]
        return round(sum(vals) / len(vals) * 100, 2) if vals else None

    pipeline = sum(float(q.total or 0) for q in open_quotes)
    won_value = sum(float(q.total or 0) for q in won_quotes)

    return DashboardStats(
        total_quotes=total,
        won=len(won_quotes),
        lost=len(lost_quotes),
        open=len(open_quotes),
        win_rate_pct=round(win_rate, 1),
        avg_margin_won_pct=avg_margin(won_quotes),
        avg_margin_lost_pct=avg_margin(lost_quotes),
        pipeline_value=round(pipeline, 2),
        won_value=round(won_value, 2),
    )


@router.get("/margin-suggestion", response_model=MarginSuggestion)
async def margin_suggestion(
    segment: str | None = None,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> MarginSuggestion:
    """
    AI preporuka marže na osnovu historijskih ponuda.
    Ako je proslijeđen segment (hotel, retail...), filtrira po klientima tog segmenta.
    """
    # Dohvati won quotes za ovaj segment
    query = (
        select(Quote.margin_pct, Quote.total)
        .join(QuoteOutcome, QuoteOutcome.quote_id == Quote.id)
        .where(Quote.org_id == org_id, QuoteOutcome.outcome == "won", Quote.margin_pct.isnot(None))
    )

    if segment:
        client_ids_result = await db.execute(
            select(Client.id).where(Client.org_id == org_id, Client.segment == segment)
        )
        client_ids = [r[0] for r in client_ids_result.all()]
        if client_ids:
            from app.db.models.project import Project
            proj_ids_result = await db.execute(
                select(Project.id).where(Project.org_id == org_id, Project.client_id.in_(client_ids))
            )
            proj_ids = [r[0] for r in proj_ids_result.all()]
            if proj_ids:
                query = query.where(Quote.project_id.in_(proj_ids))

    result = await db.execute(query)
    won_data = result.all()

    # Izgubljene za granicu
    lost_query = (
        select(Quote.margin_pct)
        .join(QuoteOutcome, QuoteOutcome.quote_id == Quote.id)
        .where(Quote.org_id == org_id, QuoteOutcome.outcome == "lost", Quote.margin_pct.isnot(None))
    )
    lost_result = await db.execute(lost_query)
    lost_margins = [float(r[0]) * 100 for r in lost_result.all() if r[0]]

    n = len(won_data)

    if n < 3:
        # Nedovoljno podataka — vrati heuristiku
        return MarginSuggestion(
            suggested_min=15.0,
            suggested_max=35.0,
            suggested_target=25.0,
            based_on_quotes=n,
            confidence="low",
            insight=f"Nedovoljno historijskih podataka ({n} ponuda). Prikazane su standardne preporuke za elektro/rasvjeta industriju.",
        )

    margins = sorted([float(r[0]) * 100 for r in won_data if r[0]])
    p25 = margins[max(0, int(len(margins) * 0.25))]
    p50 = margins[int(len(margins) * 0.5)]
    p75 = margins[min(len(margins) - 1, int(len(margins) * 0.75))]

    avg_lost = sum(lost_margins) / len(lost_margins) if lost_margins else None
    confidence = "high" if n >= 20 else "medium" if n >= 5 else "low"

    insight_parts = [f"Analiza {n} uspješnih ponuda"]
    if segment:
        insight_parts[0] += f" za segment '{segment}'"
    if avg_lost:
        insight_parts.append(f"Izgubljene ponude imale su prosječno {avg_lost:.1f}% maržu")
    if p50 > 30:
        insight_parts.append("Tržišta toleriraju višu maržu od prosjeka industrije")
    elif p50 < 15:
        insight_parts.append("Konkurencija drži marže nisko — razmotri diferencijaciju ponude")

    return MarginSuggestion(
        suggested_min=round(p25, 1),
        suggested_max=round(p75, 1),
        suggested_target=round(p50, 1),
        based_on_quotes=n,
        confidence=confidence,
        insight=". ".join(insight_parts) + ".",
    )


@router.get("/win-rate-by-segment")
async def win_rate_by_segment(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[dict]:
    """Win rate po segmentu klijenta."""
    from app.db.models.project import Project

    result = await db.execute(
        select(Client.segment, QuoteOutcome.outcome, func.count().label("cnt"))
        .join(Project, Project.client_id == Client.id)
        .join(Quote, Quote.project_id == Project.id)
        .join(QuoteOutcome, QuoteOutcome.quote_id == Quote.id)
        .where(Client.org_id == org_id)
        .group_by(Client.segment, QuoteOutcome.outcome)
    )
    rows = result.all()

    segments: dict[str, dict] = {}
    for seg, outcome, cnt in rows:
        key = seg or "ostalo"
        if key not in segments:
            segments[key] = {"segment": key, "won": 0, "lost": 0, "total": 0}
        segments[key][outcome if outcome in ("won", "lost") else "other"] = cnt
        segments[key]["total"] += cnt

    for seg in segments.values():
        total = seg["won"] + seg["lost"]
        seg["win_rate_pct"] = round(seg["won"] / total * 100, 1) if total else 0.0

    return sorted(segments.values(), key=lambda x: x["win_rate_pct"], reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# Win probability model + margin optimizer
# ─────────────────────────────────────────────────────────────────────────────

async def _historical_margins(db: AsyncSession, org_id: UUID) -> tuple[list[float], list[float]]:
    """Vrati (won_margins_pct, lost_margins_pct) iz povijesnih ponuda."""
    res = await db.execute(
        select(Quote.margin_pct, QuoteOutcome.outcome)
        .join(QuoteOutcome, QuoteOutcome.quote_id == Quote.id)
        .where(Quote.org_id == org_id, Quote.margin_pct.isnot(None),
               QuoteOutcome.outcome.in_(["won", "lost"]))
    )
    won, lost = [], []
    for margin, outcome in res.all():
        m = float(margin) * 100
        (won if outcome == "won" else lost).append(m)
    return won, lost


def _win_probability(margin_pct: float, won: list[float], lost: list[float]) -> tuple[float, str]:
    """
    Logistička krivulja: niža marža → veća vjerojatnost dobitka.
    P(win) = 1 / (1 + exp((margin - midpoint) / scale))
    Vraća (vjerojatnost 0..1, objašnjenje). margin_pct u postocima (npr. 25.0).
    """
    import math

    n = len(won) + len(lost)
    if n < 4:
        # Malo podataka — glatka krivulja oko industrijskog prosjeka (~25%)
        midpoint, scale = 25.0, 8.0
        expl = "Heuristika (malo povijesnih podataka) — industrijski prosjek ~25%"
    else:
        won_avg = sum(won) / len(won) if won else 20.0
        lost_avg = sum(lost) / len(lost) if lost else 40.0
        midpoint = (won_avg + lost_avg) / 2
        scale = max(abs(lost_avg - won_avg) / 2, 4.0)
        expl = (f"Na temelju {len(won)} dobivenih (prosj. {won_avg:.0f}%) "
                f"i {len(lost)} izgubljenih ({lost_avg:.0f}%)")

    prob = 1.0 / (1.0 + math.exp((margin_pct - midpoint) / scale))
    prob = max(0.05, min(0.95, prob))
    return round(prob, 2), expl


class WinProbability(BaseModel):
    margin_pct: float
    win_probability: float
    confidence: str
    explanation: str


@router.get("/win-probability", response_model=WinProbability)
async def win_probability(
    margin: float,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> WinProbability:
    """Vjerojatnost dobitka za zadanu maržu (%). margin = npr. 25 za 25%."""
    won, lost = await _historical_margins(db, org_id)
    prob, expl = _win_probability(margin, won, lost)
    n = len(won) + len(lost)
    conf = "high" if n >= 20 else "medium" if n >= 4 else "low"
    return WinProbability(
        margin_pct=margin, win_probability=prob, confidence=conf, explanation=expl
    )


class MarginCurvePoint(BaseModel):
    margin_pct: float
    win_probability: float
    expected_value: float   # P(win) × profit u valuti ponude


class MarginOptimizer(BaseModel):
    quote_total: float
    quote_cost: float
    current_margin_pct: float
    optimal_margin_pct: float
    optimal_expected_value: float
    curve: list[MarginCurvePoint]


@router.get("/margin-optimizer/{quote_id}", response_model=MarginOptimizer)
async def margin_optimizer(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> MarginOptimizer:
    """
    Za zadanu ponudu izračunaj krivulju: za svaku maržu (5%–50%) → vjerojatnost
    dobitka i očekivanu vrijednost P(win) × profit. Nađi maržu koja maksimizira EV.
    """
    res = await db.execute(select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id))
    quote = res.scalar_one_or_none()
    if not quote:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Ponuda nije pronađena.")

    cost = float(quote.cost_total or 0)
    total = float(quote.total or 0)
    current_margin = float(quote.margin_pct or 0) * 100

    # Ako nemamo cost, procijeni ga iz total i trenutne marže
    if cost <= 0 and total > 0 and current_margin > 0:
        cost = total * (1 - current_margin / 100)

    won, lost = await _historical_margins(db, org_id)

    curve: list[MarginCurvePoint] = []
    best_ev = -1.0
    best_margin = current_margin
    for m_int in range(5, 51, 1):
        m = float(m_int)
        prob, _ = _win_probability(m, won, lost)
        # prodajna = cost / (1 - margin); profit = prodajna - cost
        sell = cost / (1 - m / 100) if cost > 0 else 0.0
        profit = sell - cost
        ev = round(prob * profit, 2)
        if m_int % 5 == 0:  # krivulja na svakih 5% za prikaz
            curve.append(MarginCurvePoint(margin_pct=m, win_probability=prob, expected_value=ev))
        if ev > best_ev:
            best_ev = ev
            best_margin = m

    return MarginOptimizer(
        quote_total=round(total, 2),
        quote_cost=round(cost, 2),
        current_margin_pct=round(current_margin, 1),
        optimal_margin_pct=round(best_margin, 1),
        optimal_expected_value=round(best_ev, 2),
        curve=curve,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Client risk/value profile
# ─────────────────────────────────────────────────────────────────────────────

class ClientProfile(BaseModel):
    client_id: UUID
    client_name: str
    total_quotes: int
    won: int
    lost: int
    win_rate_pct: float
    avg_margin_won_pct: float | None
    total_won_value: float
    score: int          # 0..100 kompozitni "value" score
    rating: str         # A / B / C / D
    notes: list[str]


@router.get("/client-profile/{client_id}", response_model=ClientProfile)
async def client_profile(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> ClientProfile:
    """Profil klijenta: win rate, prosječna marža, vrijednost, kompozitni score."""
    from fastapi import HTTPException

    from app.db.models.project import Project

    cl = (await db.execute(
        select(Client).where(Client.id == client_id, Client.org_id == org_id)
    )).scalar_one_or_none()
    if not cl:
        raise HTTPException(status_code=404, detail="Klijent nije pronađen.")

    rows = (await db.execute(
        select(Quote.margin_pct, Quote.total, QuoteOutcome.outcome)
        .join(Project, Project.id == Quote.project_id)
        .join(QuoteOutcome, QuoteOutcome.quote_id == Quote.id)
        .where(Project.client_id == client_id, Quote.org_id == org_id)
    )).all()

    won = [(float(m) * 100 if m else None, float(t or 0)) for m, t, o in rows if o == "won"]
    lost = [r for r in rows if r[2] == "lost"]
    n_won, n_lost = len(won), len(lost)
    total_decided = n_won + n_lost
    win_rate = (n_won / total_decided * 100) if total_decided else 0.0

    won_margins = [m for m, _ in won if m is not None]
    avg_margin = round(sum(won_margins) / len(won_margins), 1) if won_margins else None
    total_won_value = round(sum(t for _, t in won), 2)

    # Kompozitni score: win rate (40%) + volumen (30%) + marža (30%)
    score = 0.0
    score += min(win_rate, 100) * 0.4
    score += min(total_won_value / 1000, 100) * 0.3  # €100k+ → max
    if avg_margin:
        score += min(avg_margin / 30 * 100, 100) * 0.3
    score_int = int(round(score))
    rating = "A" if score_int >= 70 else "B" if score_int >= 45 else "C" if score_int >= 25 else "D"

    notes: list[str] = []
    if total_decided == 0:
        notes.append("Nema zatvorenih ponuda — novi/neaktivan klijent.")
    if win_rate >= 60:
        notes.append("Visok win rate — pouzdan kupac, razmotri agresivniju maržu.")
    elif win_rate < 30 and total_decided >= 3:
        notes.append("Nizak win rate — cjenovno osjetljiv, oprez s maržom.")
    if avg_margin and avg_margin >= 25:
        notes.append("Prihvaća visoke marže — vrijedan klijent.")
    if (cl.payment_terms_days or 30) > 60:
        notes.append(f"Dugi rok plaćanja ({cl.payment_terms_days}d) — trošak kapitala.")

    return ClientProfile(
        client_id=client_id, client_name=cl.name,
        total_quotes=total_decided, won=n_won, lost=n_lost,
        win_rate_pct=round(win_rate, 1), avg_margin_won_pct=avg_margin,
        total_won_value=total_won_value, score=score_int, rating=rating,
        notes=notes or ["Nedovoljno podataka za detaljne uvide."],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard trends (revenue trend + pipeline funnel)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trends")
async def trends(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> dict:
    """Mjesečni trend (zadnjih 6 mj) + pipeline funnel po statusu."""
    from collections import defaultdict
    from datetime import datetime, timezone

    # Sve ponude
    rows = (await db.execute(
        select(Quote.created_at, Quote.total, Quote.status)
        .where(Quote.org_id == org_id)
    )).all()

    # Mjesečni: broj ponuda + vrijednost po YYYY-MM
    monthly: dict[str, dict] = defaultdict(lambda: {"count": 0, "value": 0.0})
    now = datetime.now(timezone.utc)
    # zadnjih 6 mjeseci kao prazni bucketi
    buckets = []
    for i in range(5, -1, -1):
        y = now.year
        m = now.month - i
        while m <= 0:
            m += 12
            y -= 1
        key = f"{y}-{m:02d}"
        buckets.append(key)
        monthly[key]  # init

    for created, total, status in rows:
        if not created:
            continue
        key = created.strftime("%Y-%m")
        if key in monthly:
            monthly[key]["count"] += 1
            monthly[key]["value"] += float(total or 0)

    trend = [
        {"month": k, "count": monthly[k]["count"], "value": round(monthly[k]["value"], 2)}
        for k in buckets
    ]

    # Pipeline funnel
    funnel_counts: dict[str, int] = defaultdict(int)
    for _, _, status in rows:
        funnel_counts[status] += 1

    funnel = [
        {"stage": "Nacrt",       "status": "draft",    "count": funnel_counts.get("draft", 0)},
        {"stage": "Na odobrenju","status": "review",   "count": funnel_counts.get("review", 0)},
        {"stage": "Odobreno",    "status": "approved", "count": funnel_counts.get("approved", 0)},
        {"stage": "Poslano",     "status": "sent",     "count": funnel_counts.get("sent", 0)},
        {"stage": "Dobiveno",    "status": "accepted", "count": funnel_counts.get("accepted", 0)},
    ]

    return {"monthly": trend, "funnel": funnel}


# ─────────────────────────────────────────────────────────────────────────────
# Notifikacije / "treba pažnju"
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/notifications")
async def notifications(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_current_org_id),
) -> list[dict]:
    """Stavke koje trebaju pažnju: isteci, čekaju odobrenje, ustajali nacrti."""
    from datetime import date, datetime, timedelta, timezone

    items: list[dict] = []
    today = date.today()
    soon = today + timedelta(days=7)
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=14)

    rows = (await db.execute(
        select(Quote.id, Quote.version, Quote.status, Quote.total,
               Quote.valid_until, Quote.created_at)
        .where(Quote.org_id == org_id)
    )).all()

    for qid, ver, status, total, valid_until, created in rows:
        amount = f"{float(total or 0):,.0f}"
        # Poslane ponude koje uskoro ističu
        if status == "sent" and valid_until and today <= valid_until <= soon:
            days = (valid_until - today).days
            items.append({
                "type": "expiring", "severity": "warning", "quote_id": str(qid),
                "message": f"Ponuda V{ver} (€{amount}) ističe za {days} dan(a)",
            })
        # Čekaju odobrenje
        if status == "review":
            items.append({
                "type": "awaiting_approval", "severity": "info", "quote_id": str(qid),
                "message": f"Ponuda V{ver} (€{amount}) čeka odobrenje",
            })
        # Ustajali nacrti
        if status == "draft" and created and created.replace(tzinfo=timezone.utc) < stale_cutoff:
            items.append({
                "type": "stale_draft", "severity": "muted", "quote_id": str(qid),
                "message": f"Nacrt V{ver} (€{amount}) star > 14 dana",
            })

    sev_order = {"warning": 0, "info": 1, "muted": 2}
    items.sort(key=lambda x: sev_order.get(x["severity"], 3))
    return items
