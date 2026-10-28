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
    poll_seconds: int = 60
    pages_per_job: int = 10
    api_token: str = ""

    @classmethod
    def env(cls):
        return cls(
            database_url=os.environ["SURVEILLANCE_DATABASE_URL"],
            raw_dir=Path(os.getenv("SURVEILLANCE_RAW_DIR", "./surveillance-data")),
            contracts_per_venue=int(os.getenv("SURVEILLANCE_CONTRACTS", "100")),
            api_token=os.getenv("SURVEILLANCE_API_TOKEN", ""),
        )

    def __post_init__(self):
        if self.contracts_per_venue < 1 or not 0 < self.exploration_fraction < 1:
            raise ValueError("Invalid collection budget")
