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
    legacy_capital_usd: float = 6700.0

    # Mandate V2 — risk first, evaluated over a 12-week rolling window.
    strategy_version: str = "quality_momentum_v2_2026-07-25"
    available_capital_usd: float = 1340.0
    evaluation_horizon_weeks: int = 12
    weekly_return_target_pct: float = 0.0  # Deprecated: never use a weekly profit quota as a trade trigger.
    target_alpha_pct: float = 0.0
    max_drawdown_pct: float = 0.06

    # Position and portfolio risk limits.
    max_open_positions: int = 3
    max_position_pct: float = 0.25
    risk_per_trade_pct: float = 0.0075
    max_portfolio_heat_pct: float = 0.02
    gap_slippage_buffer_pct: float = 0.0025
    min_reward_risk_ratio: float = 1.5
    min_live_score: float = 7.5
    high_conviction_enabled: bool = False  # Enable only after 30 independent matured OOS observations.
    supports_fractional_shares: bool = False
    max_same_ticker_shares: Optional[float] = None  # Share-count caps distort risk across different stock prices.
    target_cash_utilization_pct: float = 0.0  # Cash is an output of qualified opportunities, not a quota.
    block_new_buys_on_portfolio_violation: bool = True
    min_shares_for_staged_exit: float = 4.0

    # Agent behavior
    research_max_tickers: int = 10
    research_top_candidates: int = 5
    monitor_alert_threshold_pct: float = 0.08  # 8% adverse move triggers alert

    # Legacy SQLite utilities. Core workflows remain CSV/JSON-first.
    database_url: str = "sqlite:///data/investor.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
