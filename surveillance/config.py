from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    raw_dir: Path
    contracts_per_venue: int = 100
    exploration_fraction: float = 0.2
    request_interval: float = 0.6
    poll_seconds: int = 900
    pages_per_job: int = 2
    api_token: str = ""
    replay_max_trades: int = 50000
    retention_days: int = 7
    case_cooldown_seconds: int = 3600
    database_max_bytes: int = 20 * 1024**3
    raw_max_bytes: int = 5 * 1024**3
    automatic_min_cash_usd: float = 1000
    detail_seconds: int = 1800
    end_grace_hours: int = 6
    catalog_seconds: int = 21600
    closed_catalog_seconds: int = 604800
    wide_poll_seconds: int = 15
    wide_overlap_seconds: int = 60
    wide_bootstrap_seconds: int = 300
    deep_history_hours: int = 1

    @classmethod
    def env(cls):
        return cls(
            database_url=os.environ["SURVEILLANCE_DATABASE_URL"],
            raw_dir=Path(os.getenv("SURVEILLANCE_RAW_DIR", "./surveillance-data")),
            poll_seconds=int(os.getenv('SURVEILLANCE_DEEP_POLL_SECONDS','900')),
            detail_seconds=int(os.getenv('SURVEILLANCE_DETAIL_SECONDS','1800')),
            wide_poll_seconds=int(os.getenv('SURVEILLANCE_WIDE_POLL_SECONDS','15')),
            catalog_seconds=int(os.getenv("SURVEILLANCE_CATALOG_SECONDS", "21600")),
            end_grace_hours=int(os.getenv("SURVEILLANCE_END_GRACE_HOURS", "6")),
            automatic_min_cash_usd=float(os.getenv("SURVEILLANCE_AUTOMATIC_MIN_CASH_USD", "1000")),
            contracts_per_venue=int(os.getenv("SURVEILLANCE_CONTRACTS", "100")),
            api_token=os.getenv("SURVEILLANCE_API_TOKEN", ""),
            database_max_bytes=int(os.getenv("SURVEILLANCE_DATABASE_MAX_BYTES", str(20 * 1024**3))),
            raw_max_bytes=int(os.getenv("SURVEILLANCE_RAW_MAX_BYTES", str(5 * 1024**3))),
            retention_days=int(os.getenv("SURVEILLANCE_RETENTION_DAYS", "7")),
            replay_max_trades=int(os.getenv("SURVEILLANCE_REPLAY_MAX_TRADES", "50000")),
        )

    def __post_init__(self):
        if self.poll_seconds<1 or self.detail_seconds<1 or self.wide_poll_seconds<1 or self.wide_overlap_seconds<1 or self.pages_per_job<1 or self.deep_history_hours<1 or self.catalog_seconds < 1 or self.end_grace_hours < 0 or not 0 < self.automatic_min_cash_usd < float("inf") or self.database_max_bytes < 1 or self.raw_max_bytes < 1 or self.contracts_per_venue < 1 or self.retention_days < 1 or self.replay_max_trades < 1 or not 0 < self.exploration_fraction < 1:
            raise ValueError("Invalid collection budget")
