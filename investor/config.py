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

    # Portfolio sizing
    available_capital_usd: float = 6700.0  # ~1,000,000 JPY
    weekly_return_target_pct: float = 0.025  # +2.5%/週（年換算+130%）目標
    max_position_pct: float = 0.25          # 1銘柄最大25%（¥250,000 / ~$1,675）

    # Agent behavior
    research_max_tickers: int = 10
    research_top_candidates: int = 5
    monitor_alert_threshold_pct: float = 0.08  # 8% adverse move triggers alert

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
