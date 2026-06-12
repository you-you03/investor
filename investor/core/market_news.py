"""
Lightweight market/sector news collection for monitor.

This is intentionally not a fact source for decisions. It keeps a small,
evolving SQLite memory of market/industry source proxies and recent headlines
so research/decision can use them as weak context when useful.
"""

from __future__ import annotations

import re
import csv
import json
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import httpx

from investor.data.yfinance_client import YFinanceClient
from investor.utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path("data/market_news.sqlite")
PORTFOLIO_PATH = Path("data/portfolio.csv")
WATCHLIST_PATH = Path("data/watchlist.json")

ACTIVE_SOURCE_LIMIT = 3
CANDIDATE_PROBE_LIMIT = 1
ITEMS_PER_SOURCE = 2
REPORT_ITEM_LIMIT = 4
THEME_LIMIT = 3
THEME_ARTICLES_LIMIT = 5
UPPERCASE_KEYWORDS = {"HBM", "DRAM", "WFE", "D2D", "SaaS"}


@dataclass(frozen=True)
class SeedSource:
    source_type: str
    value: str
    label: str
    status: str
    priority: int


@dataclass(frozen=True)
class NewsTheme:
    key: str
    label: str
    query: str
    tickers: tuple[str, ...]
    fallback_etf: str
    priority: int


SEED_SOURCES: tuple[SeedSource, ...] = (
    SeedSource("etf", "SPY", "US broad market", "active", 100),
    SeedSource("etf", "QQQ", "Nasdaq / growth", "active", 95),
    SeedSource("etf", "SMH", "semiconductors", "active", 90),
    SeedSource("etf", "XLK", "technology", "active", 80),
    SeedSource("etf", "IGV", "cloud / software", "candidate", 70),
    SeedSource("etf", "XLF", "financials", "candidate", 65),
    SeedSource("etf", "XLE", "energy", "candidate", 60),
    SeedSource("etf", "IBB", "biotech / healthcare", "candidate", 60),
    SeedSource("etf", "XLI", "industrials", "candidate", 55),
    SeedSource("etf", "XLY", "consumer discretionary", "candidate", 55),
    SeedSource("etf", "ITA", "defense / aerospace", "candidate", 50),
    SeedSource("etf", "ARKK", "disruptive growth", "candidate", 45),
)

THEME_RULES: tuple[dict, ...] = (
    {
        "key": "ai_semiconductors",
        "label": "AI半導体・半導体製造装置",
        "terms": (
            "NVDA", "AMAT", "LRCX", "MRVL", "MU", "AVGO", "TSM", "COHR", "AAOI", "ALAB",
            "semiconductor", "半導体", "HBM", "DRAM", "WFE", "chip",
        ),
        "query": (
            "AI semiconductors, HBM memory, wafer fab equipment, Nvidia, Micron, "
            "Applied Materials, Lam Research market news"
        ),
        "fallback_etf": "SMH",
        "priority": 100,
    },
    {
        "key": "ai_datacenter_power",
        "label": "AIデータセンター電力・冷却インフラ",
        "terms": ("VRT", "VST", "data center", "データセンター", "power", "cooling", "nuclear", "電力", "冷却"),
        "query": "AI data center power cooling infrastructure Vertiv nuclear power utilities market news",
        "fallback_etf": "XLI",
        "priority": 90,
    },
    {
        "key": "cloud_enterprise_software",
        "label": "クラウド・エンタープライズソフトウェア",
        "terms": ("TEAM", "software", "SaaS", "cloud", "Atlassian", "enterprise software"),
        "query": "enterprise software SaaS cloud stocks Atlassian software spending market news",
        "fallback_etf": "IGV",
        "priority": 80,
    },
    {
        "key": "space_connectivity",
        "label": "宇宙通信・衛星通信",
        "terms": ("ASTS", "space", "satellite", "宇宙", "衛星", "D2D"),
        "query": "satellite direct to device space connectivity AST SpaceMobile market news",
        "fallback_etf": "ARKK",
        "priority": 65,
    },
    {
        "key": "airlines",
        "label": "航空・旅行需要",
        "terms": ("UAL", "airline", "travel", "航空"),
        "query": "US airlines travel demand fuel costs United Airlines market news",
        "fallback_etf": "XLY",
        "priority": 50,
    },
)

DISCOVERY_KEYWORDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("semiconductor", "chip", "nvidia", "amd", "ai accelerator"), "SMH", "semiconductors"),
    (("cloud", "software", "saas", "cybersecurity"), "IGV", "cloud / software"),
    (("bank", "yield", "fed", "credit", "loan"), "XLF", "financials"),
    (("oil", "gas", "energy", "crude"), "XLE", "energy"),
    (("biotech", "drug", "fda", "healthcare"), "IBB", "biotech / healthcare"),
    (("defense", "aerospace", "space", "missile"), "ITA", "defense / aerospace"),
    (("industrial", "manufacturing", "machinery"), "XLI", "industrials"),
)

MATERIAL_TERMS = (
    "earnings",
    "guidance",
    "outlook",
    "fed",
    "rates",
    "inflation",
    "tariff",
    "regulation",
    "ai",
    "semiconductor",
    "chip",
    "energy",
    "bank",
    "credit",
    "jobs",
    "gdp",
)


def collect_market_news(
    db_path: Path = DB_PATH,
    yf_client: YFinanceClient | None = None,
    today: date | None = None,
) -> dict:
    """Collect a small market/sector news set and evolve source scores."""
    collector = MarketNewsCollector(db_path=db_path, yf_client=yf_client)
    return collector.collect(today=today or date.today())


def load_recent_market_news(db_path: Path = DB_PATH, limit: int = REPORT_ITEM_LIMIT) -> dict:
    """Load recent selected market news without fetching new data."""
    if not db_path.exists():
        return {
            "db_path": str(db_path),
            "disclaimer": "参考ニュースDB未作成。monitor実行後に利用可能。",
            "items": [],
        }

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
              i.run_date,
              s.value AS source,
              s.label AS source_label,
              i.title,
              i.publisher,
              i.url,
              i.domain,
              i.published_at,
              i.summary,
              i.relevance_score
            FROM market_news_items i
            JOIN market_news_sources s ON s.id = i.source_id
            WHERE i.selected_for_monitor = 1
            ORDER BY i.run_date DESC, i.relevance_score DESC, i.published_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        item["key_point"] = _japanese_key_point(
            summary=str(item.get("summary") or ""),
            title=str(item.get("title") or ""),
            source_label=str(item.get("source_label") or ""),
        )
        items.append(item)

    return {
        "db_path": str(db_path),
        "disclaimer": "参考ニュース。未検証のためファクト扱いしない。",
        "items": items,
    }


class MarketNewsCollector:
    def __init__(self, db_path: Path = DB_PATH, yf_client: YFinanceClient | None = None) -> None:
        self.db_path = db_path
        self.yf = yf_client or YFinanceClient()
        self._perplexity_disabled = False

    def collect(self, today: date) -> dict:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            self._ensure_schema(conn)
            self._seed_sources(conn)
            self._evolve_sources(conn)

            themes = derive_relevant_themes()
            fetched_items = self._collect_theme_items(conn, themes, today)
            if not fetched_items:
                fetched_items = self._collect_fallback_market_items(conn, today)

            selected = self._select_report_items(fetched_items)
            self._mark_selected(conn, selected)
            self._discover_candidates(conn, selected)
            self._evolve_sources(conn)
            source_stats = self._source_stats(conn)

        return {
            "date": today.isoformat(),
            "db_path": str(self.db_path),
            "disclaimer": "参考ニュース。未検証のためファクト扱いしない。",
            "collection_limits": {
                "theme_limit": THEME_LIMIT,
                "active_sources": ACTIVE_SOURCE_LIMIT,
                "candidate_probe_sources": CANDIDATE_PROBE_LIMIT,
                "items_per_source": ITEMS_PER_SOURCE,
                "report_items": REPORT_ITEM_LIMIT,
            },
            "themes": [theme.__dict__ for theme in themes],
            "items": selected,
            "source_stats": source_stats,
        }

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_news_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                value TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'candidate',
                priority INTEGER NOT NULL DEFAULT 50,
                hit_count INTEGER NOT NULL DEFAULT 0,
                selected_count INTEGER NOT NULL DEFAULT 0,
                miss_streak INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_seen_at TEXT
            );

            CREATE TABLE IF NOT EXISTS market_news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                run_date TEXT NOT NULL,
                title TEXT NOT NULL,
                publisher TEXT,
                url TEXT NOT NULL UNIQUE,
                domain TEXT,
                published_at TEXT,
                summary TEXT,
                relevance_score REAL NOT NULL DEFAULT 0,
                selected_for_monitor INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES market_news_sources(id)
            );
            """
        )

    def _seed_sources(self, conn: sqlite3.Connection) -> None:
        now = datetime.utcnow().isoformat()
        for source in SEED_SOURCES:
            conn.execute(
                """
                INSERT OR IGNORE INTO market_news_sources
                  (source_type, value, label, status, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (source.source_type, source.value, source.label, source.status, source.priority, now, now),
            )

    def _sources_to_fetch(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        active = conn.execute(
            """
            SELECT * FROM market_news_sources
            WHERE status = 'active'
            ORDER BY priority DESC, selected_count DESC, hit_count DESC, value ASC
            LIMIT ?
            """,
            (ACTIVE_SOURCE_LIMIT,),
        ).fetchall()
        candidates = conn.execute(
            """
            SELECT * FROM market_news_sources
            WHERE status = 'candidate'
            ORDER BY priority DESC, selected_count DESC, hit_count DESC, value ASC
            LIMIT ?
            """,
            (CANDIDATE_PROBE_LIMIT,),
        ).fetchall()
        return [*active, *candidates]

    def _collect_theme_items(
        self,
        conn: sqlite3.Connection,
        themes: list[NewsTheme],
        today: date,
    ) -> list[dict]:
        items: list[dict] = []
        for theme in themes[:THEME_LIMIT]:
            source = self._upsert_theme_source(conn, theme)
            summary_item = self._fetch_theme_summary(theme, today)
            if summary_item:
                self._record_source_result(conn, int(source["id"]), True)
                saved = self._save_item(conn, source, summary_item, today)
                if saved:
                    saved["theme"] = theme.label
                    saved["tickers"] = list(theme.tickers)
                    items.append(saved)
                continue

            fallback_items = self._fetch_theme_fallback(theme)
            self._record_source_result(conn, int(source["id"]), bool(fallback_items))
            for item in fallback_items:
                saved = self._save_item(conn, source, item, today)
                if saved:
                    saved["theme"] = theme.label
                    saved["tickers"] = list(theme.tickers)
                    items.append(saved)
        return items

    def _collect_fallback_market_items(self, conn: sqlite3.Connection, today: date) -> list[dict]:
        fetched_items: list[dict] = []
        sources = self._sources_to_fetch(conn)[:2]
        for source in sources:
            items = self._fetch_source(source)[:1]
            self._record_source_result(conn, int(source["id"]), bool(items))
            for item in items:
                saved = self._save_item(conn, source, item, today)
                if saved:
                    fetched_items.append(saved)
        return fetched_items

    def _fetch_theme_fallback(self, theme: NewsTheme) -> list[dict]:
        tickers = list(theme.tickers[:3]) or [theme.fallback_etf]
        items: list[dict] = []
        for ticker in tickers:
            try:
                for item in self.yf.get_news(ticker, max_items=1):
                    copied = dict(item)
                    copied["title"] = f"{ticker}: {copied.get('title', '')}"
                    items.append(copied)
            except Exception as e:
                logger.warning("theme fallback news failed for %s/%s: %s", theme.key, ticker, e)
        if items:
            return items[:ITEMS_PER_SOURCE]
        return self.yf.get_news(theme.fallback_etf, max_items=1)

    def _upsert_theme_source(self, conn: sqlite3.Connection, theme: NewsTheme) -> sqlite3.Row:
        now = datetime.utcnow().isoformat()
        value = theme.fallback_etf
        conn.execute(
            """
            INSERT INTO market_news_sources
              (source_type, value, label, status, priority, created_at, updated_at)
            VALUES ('theme', ?, ?, 'active', ?, ?, ?)
            ON CONFLICT(value) DO UPDATE SET
              source_type = 'theme',
              label = excluded.label,
              status = 'active',
              priority = excluded.priority,
              updated_at = excluded.updated_at
            """,
            (value, theme.label, theme.priority, now, now),
        )
        row = conn.execute("SELECT * FROM market_news_sources WHERE value = ?", (value,)).fetchone()
        if row is None:
            raise RuntimeError(f"Failed to upsert market news source: {value}")
        return row

    def _fetch_theme_summary(self, theme: NewsTheme, today: date) -> dict | None:
        if not self._perplexity_disabled:
            try:
                from investor.clients.news_client import PerplexityClient
            except Exception:
                PerplexityClient = None  # type: ignore[assignment]

            if PerplexityClient is not None and PerplexityClient.is_available():
                ticker_text = ", ".join(theme.tickers) if theme.tickers else "関連銘柄なし"
                query = (
                    f"{theme.query}\n\n"
                    f"対象テーマ: {theme.label}\n"
                    f"関連銘柄: {ticker_text}\n"
                    "直近3日程度の重要ニュースだけを調べてください。\n"
                    "日本語で、投資判断の参考メモとして出力してください。\n"
                    "形式:\n"
                    "- 要約: 2文以内\n"
                    "- ポートフォリオ/ウォッチリストへの関係: 1文\n"
                    "- 注意点: 未確認または反対材料があれば1文\n"
                    "事実と推測を混ぜず、断定しすぎないでください。"
                )
                try:
                    result = PerplexityClient().search(query, max_tokens=700)
                except Exception as e:
                    logger.warning("Perplexity theme summary failed for %s: %s", theme.key, e)
                    self._perplexity_disabled = True
                    result = None
                if result:
                    return {
                        "title": f"{theme.label}の直近ニュース要約",
                        "source": "Perplexity Sonar",
                        "url": f"perplexity://market-news/{today.isoformat()}/{theme.key}",
                        "published_at": datetime.utcnow().isoformat(),
                        "summary": result,
                    }
                self._perplexity_disabled = True

        if self.yf.__class__ is not YFinanceClient:
            return None

        rss_item = self._fetch_theme_rss_summary(theme, today)
        if rss_item:
            return rss_item
        return None

    def _fetch_theme_rss_summary(self, theme: NewsTheme, today: date) -> dict | None:
        articles = self._fetch_google_news_rss(theme)
        if not articles:
            return None
        summary = _build_theme_memo(theme, articles)
        return {
            "title": f"{theme.label}の関連ニュースメモ",
            "source": "Google News RSS",
            "url": articles[0].get("url") or f"rss://market-news/{today.isoformat()}/{theme.key}",
            "published_at": articles[0].get("published_at") or datetime.utcnow().isoformat(),
            "summary": summary,
            "source_articles": articles,
        }

    def _fetch_google_news_rss(self, theme: NewsTheme) -> list[dict]:
        ticker_query = " OR ".join(theme.tickers[:4])
        query = f"({theme.query}) when:7d"
        if ticker_query:
            query += f" ({ticker_query})"
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        try:
            response = httpx.get(url, timeout=15.0, follow_redirects=True)
            response.raise_for_status()
        except Exception as e:
            logger.warning("Google News RSS failed for %s: %s", theme.key, e)
            return []

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as e:
            logger.warning("Google News RSS parse failed for %s: %s", theme.key, e)
            return []

        articles: list[dict] = []
        for node in root.findall(".//item")[:THEME_ARTICLES_LIMIT]:
            title = _clean_text(node.findtext("title") or "")
            source = _clean_text(node.findtext("source") or "")
            articles.append({
                "title": title,
                "source": source or _extract_source_from_google_title(title),
                "url": _clean_text(node.findtext("link") or ""),
                "published_at": _clean_text(node.findtext("pubDate") or ""),
                "summary": _clean_text(node.findtext("description") or ""),
            })
        return [article for article in articles if article.get("title")]

    def _fetch_source(self, source: sqlite3.Row) -> list[dict]:
        value = str(source["value"])
        try:
            return self.yf.get_news(value, max_items=ITEMS_PER_SOURCE)
        except Exception as e:
            logger.warning("market news fetch failed for %s: %s", value, e)
            return []

    def _record_source_result(self, conn: sqlite3.Connection, source_id: int, has_items: bool) -> None:
        now = datetime.utcnow().isoformat()
        if has_items:
            conn.execute(
                """
                UPDATE market_news_sources
                SET hit_count = hit_count + 1,
                    miss_streak = 0,
                    last_seen_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, source_id),
            )
        else:
            conn.execute(
                """
                UPDATE market_news_sources
                SET miss_streak = miss_streak + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, source_id),
            )

    def _save_item(
        self,
        conn: sqlite3.Connection,
        source: sqlite3.Row,
        item: dict,
        today: date,
    ) -> dict | None:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            return None

        if item.get("source_articles"):
            summary = _clean_multiline_text(str(item.get("summary") or ""))
        else:
            summary = _clean_text(str(item.get("summary") or ""))
        key_point = _japanese_key_point(
            summary=summary,
            title=title,
            source_label=str(source["label"]),
        )
        score = _score_item(title=title, summary=summary)
        domain = urlparse(url).netloc
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO market_news_items
              (source_id, run_date, title, publisher, url, domain, published_at, summary, relevance_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              source_id = excluded.source_id,
              run_date = excluded.run_date,
              title = excluded.title,
              publisher = excluded.publisher,
              domain = excluded.domain,
              published_at = excluded.published_at,
              summary = excluded.summary,
              relevance_score = excluded.relevance_score
            """,
            (
                int(source["id"]),
                today.isoformat(),
                title,
                item.get("source"),
                url,
                domain,
                item.get("published_at"),
                summary[:1200],
                score,
                now,
            ),
        )
        return {
            "source": source["value"],
            "source_label": source["label"],
            "title": title,
            "publisher": item.get("source") or domain,
            "url": url,
            "domain": domain,
            "published_at": item.get("published_at"),
            "summary": summary if item.get("source_articles") else summary[:220],
            "key_point": key_point,
            "source_articles": item.get("source_articles") or [],
            "relevance_score": score,
            "source_id": int(source["id"]),
        }

    def _select_report_items(self, items: list[dict]) -> list[dict]:
        deduped: dict[str, dict] = {}
        for item in items:
            deduped.setdefault(item["url"], item)
        selected = sorted(
            deduped.values(),
            key=lambda item: (
                float(item.get("relevance_score") or 0),
                str(item.get("published_at") or ""),
            ),
            reverse=True,
        )[:REPORT_ITEM_LIMIT]
        for item in selected:
            item.pop("source_id", None)
        return selected

    def _mark_selected(self, conn: sqlite3.Connection, selected: list[dict]) -> None:
        now = datetime.utcnow().isoformat()
        for item in selected:
            row = conn.execute(
                "SELECT source_id FROM market_news_items WHERE url = ?",
                (item["url"],),
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                "UPDATE market_news_items SET selected_for_monitor = 1 WHERE url = ?",
                (item["url"],),
            )
            conn.execute(
                """
                UPDATE market_news_sources
                SET selected_count = selected_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, int(row["source_id"])),
            )

    def _discover_candidates(self, conn: sqlite3.Connection, selected: list[dict]) -> None:
        text = " ".join(str(item.get("title", "")) for item in selected).lower()
        now = datetime.utcnow().isoformat()
        for terms, ticker, label in DISCOVERY_KEYWORDS:
            if any(term in text for term in terms):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO market_news_sources
                      (source_type, value, label, status, priority, created_at, updated_at)
                    VALUES ('etf', ?, ?, 'candidate', 50, ?, ?)
                    """,
                    (ticker, label, now, now),
                )

    def _evolve_sources(self, conn: sqlite3.Connection) -> None:
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE market_news_sources
            SET status = 'active', updated_at = ?
            WHERE status = 'candidate'
              AND (selected_count >= 1 OR hit_count >= 2)
            """,
            (now,),
        )
        conn.execute(
            """
            UPDATE market_news_sources
            SET status = 'paused', updated_at = ?
            WHERE status = 'active'
              AND miss_streak >= 3
              AND priority < 90
            """,
            (now,),
        )

        active_rows = conn.execute(
            """
            SELECT id FROM market_news_sources
            WHERE status = 'active'
            ORDER BY
              (priority + selected_count * 8 + hit_count * 2 - miss_streak * 10) DESC,
              value ASC
            """
        ).fetchall()
        overflow = active_rows[ACTIVE_SOURCE_LIMIT:]
        for row in overflow:
            conn.execute(
                "UPDATE market_news_sources SET status = 'candidate', updated_at = ? WHERE id = ?",
                (now, int(row["id"])),
            )

    def _source_stats(self, conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute(
            """
            SELECT value, label, status, priority, hit_count, selected_count, miss_streak, last_seen_at
            FROM market_news_sources
            ORDER BY status ASC, priority DESC, selected_count DESC, value ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def _score_item(title: str, summary: str) -> float:
    text = f"{title} {summary}".lower()
    score = 1.0
    score += sum(1.0 for term in MATERIAL_TERMS if term in text)
    if re.search(r"\b(fed|cpi|jobs|gdp|inflation|rates)\b", text):
        score += 2.0
    if re.search(r"\b(earnings|guidance|outlook)\b", text):
        score += 1.5
    return round(score, 2)


def _build_theme_memo(theme: NewsTheme, articles: list[dict]) -> str:
    text = " ".join(
        f"{article.get('title', '')} {article.get('summary', '')}"
        for article in articles
    )
    lowered = text.lower()
    themes = _detect_themes(lowered)
    headlines = [_strip_google_source(str(article.get("title") or "")) for article in articles[:3]]
    headline_text = " / ".join(f"「{headline}」" for headline in headlines if headline)
    tickers = ", ".join(theme.tickers[:6]) if theme.tickers else "関連銘柄なし"

    if themes:
        topic = "、".join(themes[:4])
    else:
        topic = "テーマ周辺の値動き・需給・業績材料"

    summary = (
        f"- 要約: {theme.label}では、{topic}が主な論点。"
        f"参照見出しは {headline_text}。"
    )
    relation = (
        f"- 関係: 関連銘柄は {tickers}。"
        "保有・監視銘柄の個別材料というより、同じテーマ内の地合いと資金の向きを見る参考材料。"
    )
    caution = (
        "- 注意点: RSS見出しと短い説明から作った未検証メモ。"
        "売買判断では、個別銘柄の決算、ガイダンス、価格、出来高で再確認する。"
    )
    return "\n".join([summary, relation, caution])


def derive_relevant_themes(
    portfolio_path: Path = PORTFOLIO_PATH,
    watchlist_path: Path = WATCHLIST_PATH,
) -> list[NewsTheme]:
    """Derive a small set of news themes from open positions and active watchlist items."""
    rows = _load_relevant_security_rows(portfolio_path=portfolio_path, watchlist_path=watchlist_path)
    if not rows:
        return [
            NewsTheme(
                key="broad_market",
                label="米国株市場全体",
                query="US stock market macro rates earnings broad market news",
                tickers=(),
                fallback_etf="SPY",
                priority=10,
            )
        ]

    scored: dict[str, dict] = {}
    for rule in THEME_RULES:
        score = 0
        tickers: set[str] = set()
        ticker_terms = {
            str(term).upper()
            for term in rule["terms"]
            if str(term).isalnum() and str(term).upper() == str(term) and str(term) not in UPPERCASE_KEYWORDS
        }
        keyword_terms = tuple(
            str(term).lower()
            for term in rule["terms"]
            if str(term).upper() != str(term) or str(term) in UPPERCASE_KEYWORDS or len(str(term)) > 5
        )
        for row in rows:
            ticker = str(row.get("ticker", "")).upper()
            context = " ".join(str(row.get(key, "")) for key in ("note", "reason", "signal_type")).lower()
            ticker_matched = ticker in ticker_terms
            keyword_matched = any(term in context for term in keyword_terms)
            if ticker_matched or keyword_matched:
                score += 3 if row.get("source_group") == "portfolio" else 1
                tickers.add(ticker)
        if score:
            scored[rule["key"]] = {
                "score": score + int(rule["priority"]),
                "rule": rule,
                "tickers": tuple(sorted(t for t in tickers if t)),
            }

    themes = []
    for item in sorted(scored.values(), key=lambda value: value["score"], reverse=True)[:THEME_LIMIT]:
        rule = item["rule"]
        themes.append(
            NewsTheme(
                key=rule["key"],
                label=rule["label"],
                query=rule["query"],
                tickers=item["tickers"],
                fallback_etf=rule["fallback_etf"],
                priority=int(item["score"]),
            )
        )
    return themes


def _load_relevant_security_rows(portfolio_path: Path, watchlist_path: Path) -> list[dict]:
    rows: list[dict] = []
    if portfolio_path.exists():
        try:
            with portfolio_path.open() as f:
                for row in csv.DictReader(f):
                    if row.get("status") == "open":
                        row["source_group"] = "portfolio"
                        rows.append(row)
        except Exception as e:
            logger.warning("Failed to read portfolio themes: %s", e)

    if watchlist_path.exists():
        try:
            data = json.loads(watchlist_path.read_text())
            for item in data.get("items", []):
                if item.get("status") == "active" or item.get("pipeline_status") in {"research_queued", "decision_queued"}:
                    row = dict(item)
                    row["source_group"] = "watchlist"
                    rows.append(row)
        except Exception as e:
            logger.warning("Failed to read watchlist themes: %s", e)
    return rows


def _clean_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_multiline_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _strip_google_source(title: str) -> str:
    # Google News RSS often returns "Headline - Publisher".
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title.strip()


def _extract_source_from_google_title(title: str) -> str:
    if " - " in title:
        return title.rsplit(" - ", 1)[1].strip()
    return ""


def _short_key_point(summary: str, title: str, max_chars: int = 180) -> str:
    cleaned = _clean_text(summary)
    if not cleaned:
        cleaned = _clean_text(title)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _japanese_key_point(summary: str, title: str, source_label: str, max_chars: int = 900) -> str:
    """Create a cheap Japanese memo without using an LLM translation call."""
    cleaned_summary = _clean_multiline_text(summary)
    if _contains_japanese(cleaned_summary):
        if len(cleaned_summary) <= max_chars:
            return cleaned_summary
        return cleaned_summary[: max_chars - 3].rstrip() + "..."

    text = _clean_text(f"{title} {summary}")
    lowered = text.lower()
    themes = _detect_themes(lowered)
    entities = _extract_entities(text)

    parts = []
    if entities:
        parts.append("/".join(entities[:5]))
    elif source_label:
        parts.append(source_label)

    if themes:
        parts.append("・".join(themes[:3]))

    numbers = _extract_numbers(text)
    if numbers:
        parts.append("主な数字: " + "、".join(numbers[:3]))

    if parts:
        memo = " / ".join(parts) + "に関する記事。"
    else:
        memo = _short_key_point(summary=summary, title=title, max_chars=max_chars)

    if len(memo) <= max_chars:
        return memo
    return memo[: max_chars - 3].rstrip() + "..."


def _detect_themes(lowered: str) -> list[str]:
    theme_rules = [
        (("fed", "rate", "rates", "yield", "treasury"), "金利・Fed"),
        (("cpi", "inflation", "jobs", "gdp"), "マクロ指標"),
        (("nasdaq", "s&p", "dow", "market"), "市場全体の値動き"),
        (("tech", "technology", "software", "cloud"), "テック株"),
        (("semiconductor", "chip", "ai accelerator", "nvidia", "amd"), "半導体・AI"),
        (("earnings", "guidance", "outlook"), "決算・ガイダンス"),
        (("etf", "flows", "inflows", "outflows"), "ETF資金フロー"),
        (("ipo", "spacex"), "IPO・指数採用"),
        (("bank", "credit", "loan"), "金融・信用"),
        (("oil", "energy", "crude", "gas"), "エネルギー"),
        (("regulation", "tariff"), "規制・関税"),
    ]
    themes: list[str] = []
    for needles, label in theme_rules:
        if any(needle in lowered for needle in needles):
            themes.append(label)
    return themes


def _extract_entities(text: str) -> list[str]:
    known = [
        "Nasdaq",
        "S&P 500",
        "Dow",
        "Fed",
        "CPI",
        "SpaceX",
        "Nvidia",
        "AMD",
        "Tesla",
        "Google",
        "Meta",
    ]
    entities = [name for name in known if name.lower() in text.lower()]
    tickers = re.findall(r"\b[A-Z]{2,5}\b", text)
    for ticker in tickers:
        if ticker not in {"ETF", "IPO", "CEO", "CPI", "GDP"} and ticker not in entities:
            entities.append(ticker)
    return entities


def _extract_numbers(text: str) -> list[str]:
    candidates = re.findall(r"[-+]?\$?\d+(?:\.\d+)?%?[MB]?", text)
    return [
        item
        for item in candidates
        if "$" in item or "%" in item or item.endswith(("M", "B")) or item.startswith(("+", "-"))
    ]


def _contains_japanese(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text))
