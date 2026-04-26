"""
FastAPI server exposing portfolio data for the Next.js dashboard.

Run with:
  uvicorn investor.api:app --reload --port 8000
"""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import select

from investor.db.database import create_db, get_session
from investor.db.models import InvestmentProposal, MonitorAlert, Position, ProposalResult, WatchlistItem

app = FastAPI(title="Investor API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    create_db()


@app.get("/api/portfolio")
def get_portfolio() -> list[dict]:
    """Return all open positions."""
    with get_session() as session:
        positions = session.exec(
            select(Position).where(Position.status == "open")
        ).all()
    return [
        {
            "id": p.id,
            "ticker": p.ticker,
            "shares": p.shares,
            "entry_price": p.entry_price,
            "entry_date": p.entry_date.isoformat(),
            "target_price": p.target_price,
            "stop_loss": p.stop_loss,
            "status": p.status,
            "note": p.note,
        }
        for p in positions
    ]


@app.get("/api/proposals")
def get_proposals(limit: int = 20) -> list[dict]:
    """Return recent investment proposals."""
    with get_session() as session:
        proposals = session.exec(
            select(InvestmentProposal)
            .order_by(InvestmentProposal.created_at.desc())
            .limit(limit)
        ).all()
    return [
        {
            "id": p.id,
            "ticker": p.ticker,
            "action": p.action,
            "conviction": p.conviction,
            "shares_suggested": p.shares_suggested,
            "entry_price_range": p.entry_price_range,
            "target_price": p.target_price,
            "stop_loss": p.stop_loss,
            "position_size_usd": p.position_size_usd,
            "rationale": p.rationale,
            "time_horizon": p.time_horizon,
            "human_decision": p.human_decision,
            "created_at": p.created_at.isoformat(),
        }
        for p in proposals
    ]


@app.get("/api/alerts")
def get_alerts(limit: int = 50, severity: str | None = None) -> list[dict]:
    """Return recent monitor alerts, optionally filtered by severity."""
    with get_session() as session:
        query = select(MonitorAlert).order_by(MonitorAlert.created_at.desc()).limit(limit)
        alerts = session.exec(query).all()
    filtered = [a for a in alerts if severity is None or a.severity == severity.upper()]
    return [
        {
            "id": a.id,
            "ticker": a.ticker,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "current_price": a.current_price,
            "unrealized_pnl_pct": a.unrealized_pnl_pct,
            "message": a.message,
            "created_at": a.created_at.isoformat(),
        }
        for a in filtered
    ]


class ProposalResultCreate(BaseModel):
    entry_price: float
    exit_price: float
    exit_date: str  # ISO date string
    actual_return_pct: float
    outcome: str  # "win" | "loss" | "neutral"
    notes: str | None = None


@app.post("/api/proposals/{proposal_id}/result")
def record_proposal_result(proposal_id: int, body: ProposalResultCreate) -> dict:
    """Record the actual outcome of an investment proposal (for Reflection loop)."""
    with get_session() as session:
        proposal = session.get(InvestmentProposal, proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if body.outcome not in {"win", "loss", "neutral"}:
            raise HTTPException(status_code=400, detail="outcome must be win, loss, or neutral")
        result = ProposalResult(
            proposal_id=proposal_id,
            ticker=proposal.ticker,
            entry_price=body.entry_price,
            exit_price=body.exit_price,
            exit_date=date.fromisoformat(body.exit_date),
            actual_return_pct=body.actual_return_pct,
            outcome=body.outcome,
            notes=body.notes,
        )
        session.add(result)
        session.commit()
        session.refresh(result)
        return {"id": result.id, "ticker": result.ticker, "outcome": result.outcome}


@app.get("/api/proposals/{proposal_id}/result")
def get_proposal_result(proposal_id: int) -> dict:
    """Retrieve the recorded outcome of a proposal."""
    with get_session() as session:
        result = session.exec(
            select(ProposalResult).where(ProposalResult.proposal_id == proposal_id)
        ).first()
        if not result:
            raise HTTPException(status_code=404, detail="No result recorded for this proposal")
        return {
            "id": result.id,
            "proposal_id": result.proposal_id,
            "ticker": result.ticker,
            "entry_price": result.entry_price,
            "exit_price": result.exit_price,
            "exit_date": result.exit_date.isoformat() if result.exit_date else None,
            "actual_return_pct": result.actual_return_pct,
            "outcome": result.outcome,
            "notes": result.notes,
        }


@app.get("/api/results")
def list_results(limit: int = 20) -> list[dict]:
    """Return recent closed proposal results (for performance tracking)."""
    with get_session() as session:
        results = session.exec(
            select(ProposalResult)
            .order_by(ProposalResult.exit_date.desc())
            .limit(limit)
        ).all()
    return [
        {
            "id": r.id,
            "proposal_id": r.proposal_id,
            "ticker": r.ticker,
            "entry_price": r.entry_price,
            "exit_price": r.exit_price,
            "exit_date": r.exit_date.isoformat() if r.exit_date else None,
            "actual_return_pct": r.actual_return_pct,
            "outcome": r.outcome,
        }
        for r in results
    ]


@app.get("/api/watchlist")
def get_watchlist() -> list[dict]:
    """Return active watchlist items."""
    with get_session() as session:
        items = session.exec(
            select(WatchlistItem)
            .where(WatchlistItem.status == "active")
            .order_by(WatchlistItem.added_at.desc())
        ).all()
    return [
        {
            "id": i.id,
            "ticker": i.ticker,
            "added_at": i.added_at.isoformat(),
            "reason": i.reason,
            "status": i.status,
        }
        for i in items
    ]
