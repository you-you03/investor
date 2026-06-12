from pathlib import Path


class FakeYFinanceClient:
    def get_news(self, ticker: str, max_items: int = 10) -> list[dict]:
        return [
            {
                "title": f"{ticker} earnings and Fed rates move market",
                "source": "Example News",
                "url": f"https://example.com/{ticker.lower()}-1",
                "published_at": "2026-06-06T12:00:00Z",
                "summary": "Lightweight market context only.",
            },
            {
                "title": f"{ticker} sector outlook mentions AI chips",
                "source": "Example News",
                "url": f"https://example.com/{ticker.lower()}-2",
                "published_at": "2026-06-06T11:00:00Z",
                "summary": "Not decision evidence.",
            },
        ][:max_items]


def test_collect_market_news_creates_bounded_reference_db(tmp_path: Path):
    from datetime import date

    from investor.core.market_news import collect_market_news

    db_path = tmp_path / "market_news.sqlite"
    result = collect_market_news(
        db_path=db_path,
        yf_client=FakeYFinanceClient(),
        today=date(2026, 6, 6),
    )

    assert db_path.exists()
    assert result["disclaimer"].startswith("参考ニュース")
    assert len(result["items"]) <= result["collection_limits"]["report_items"]
    assert result["collection_limits"]["theme_limit"] == 3
    assert result["collection_limits"]["active_sources"] == 3
    assert result["collection_limits"]["candidate_probe_sources"] == 1
    assert all("url" in item and "title" in item for item in result["items"])
    assert all(item["key_point"] for item in result["items"])


def test_load_recent_market_news_reads_selected_items(tmp_path: Path):
    from datetime import date

    from investor.core.market_news import collect_market_news, load_recent_market_news

    db_path = tmp_path / "market_news.sqlite"
    collect_market_news(
        db_path=db_path,
        yf_client=FakeYFinanceClient(),
        today=date(2026, 6, 6),
    )

    recent = load_recent_market_news(db_path=db_path, limit=3)

    assert recent["disclaimer"].startswith("参考ニュース")
    assert len(recent["items"]) == 3
    assert recent["items"][0]["run_date"] == "2026-06-06"
    assert recent["items"][0]["key_point"]


def test_derive_relevant_themes_from_portfolio_and_watchlist(tmp_path: Path):
    import csv
    import json

    from investor.core.market_news import derive_relevant_themes

    portfolio_path = tmp_path / "portfolio.csv"
    with portfolio_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "status", "note", "signal_type"])
        writer.writeheader()
        writer.writerow({
            "ticker": "NVDA",
            "status": "open",
            "note": "AI半導体 Blackwell",
            "signal_type": "technical_breakout",
        })
        writer.writerow({
            "ticker": "VRT",
            "status": "open",
            "note": "AIデータセンター電力・冷却インフラ",
            "signal_type": "watchlist_escalate",
        })

    watchlist_path = tmp_path / "watchlist.json"
    watchlist_path.write_text(json.dumps({
        "items": [
            {
                "ticker": "TEAM",
                "status": "active",
                "reason": "enterprise software SaaS",
                "pipeline_status": "research_queued",
            }
        ]
    }))

    themes = derive_relevant_themes(portfolio_path=portfolio_path, watchlist_path=watchlist_path)
    labels = [theme.label for theme in themes]

    assert "AI半導体・半導体製造装置" in labels
    assert "AIデータセンター電力・冷却インフラ" in labels
