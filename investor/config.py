from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Notification-only dependency. Read-only and paper flows must work without it.
    slack_webhook_url: Optional[str] = None

    # Optional API Keys
    anthropic_api_key: Optional[str] = None
    perplexity_api_key: Optional[str] = None
    xai_api_key: Optional[str] = None

    # Supabase persistence. Optional until migration is applied.
    supabase_url: Optional[str] = None
    supabase_service_role_key: Optional[str] = None

    # Portfolio profiles. The 200,000 JPY portfolio is the default operating book.
    default_portfolio_path: str = "data/portfolio_20man.csv"
    legacy_portfolio_path: str = "data/portfolio_100man.csv"

    # Portfolio sizing
    available_capital_usd: float = 1340.0  # ~200,000 JPY using the mandate's ¥1,000,000 ~= $6,700 assumption
    weekly_return_target_pct: float = 0.025  # +2.5%/週（年換算+130%）目標
    max_position_pct: float = 1.0           # 20万円枠は総額上限 + 同一銘柄2株上限で制御
    max_same_ticker_shares: float = 2.0
    target_cash_utilization_pct: float = 0.85

    # Agent behavior
    research_max_tickers: int = 10
    research_top_candidates: int = 5
    monitor_alert_threshold_pct: float = 0.08  # 8% adverse move triggers alert

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
