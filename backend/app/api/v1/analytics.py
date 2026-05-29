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
