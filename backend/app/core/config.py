from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Prediction Market API"
    app_env: str = "development"
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    data_api_base_url: str = "https://data-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    kalshi_base_url: str = "https://external-api.kalshi.com/trade-api/v2"
    featured_market_slug: str = "california-governor-election-2026"
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    live_stream_enabled: bool = True
    live_stream_initial_dump: bool = True
    live_stream_max_markets: int = 6
    live_stream_idle_ttl_seconds: int = 300
    live_stream_cleanup_interval_seconds: int = 60
    live_stream_metrics_history_limit: int = 240
    allow_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )
    request_timeout_seconds: float = 8.0
    polymarket_market_cache_ttl_seconds: int = 300
    polymarket_market_stale_if_error_seconds: int = 3600
    polymarket_orderbook_cache_ttl_seconds: int = 2
    polymarket_trades_cache_ttl_seconds: int = 3
    polymarket_history_cache_ttl_seconds: int = 300
    polymarket_realtime_stale_if_error_seconds: int = 15
    kalshi_event_cache_ttl_seconds: int = 15
    kalshi_analytics_cache_ttl_seconds: int = 10
    kalshi_history_cache_ttl_seconds: int = 300
    kalshi_stale_if_error_seconds: int = 300
    market_catalog_sync_interval_seconds: int = 300
    market_catalog_stale_if_error_seconds: int = 3600
    market_catalog_page_size: int = 100
    market_catalog_max_pages: int = 20
    monitoring_enabled: bool = True
    monitoring_hot_markets_per_venue: int = 20
    monitoring_warm_markets_per_venue: int = 120
    monitoring_polymarket_hot_streams: int = 3
    monitoring_hot_refresh_seconds: int = 15
    monitoring_warm_refresh_seconds: int = 60
    monitoring_scheduler_tick_seconds: float = 1.0
    monitoring_max_refreshes_per_tick: int = 4
    polymarket_request_rate_per_second: float = 8.0
    polymarket_request_burst: int = 16
    kalshi_request_rate_per_second: float = 8.0
    kalshi_request_burst: int = 16

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
