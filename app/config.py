from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    elasticsearch_url: str = "http://localhost:9200"
    index_name: str = "products"
    database_url: str = "postgresql+asyncpg://search_app:search_pw@localhost:5432/search_service"

    # Bayesian smoothing prior for CTR-based popularity (see ranking.py) --
    # equivalent to assuming every product starts with this many "virtual"
    # impressions at the site-wide average CTR, so new/low-traffic products
    # don't get wild scores from a tiny sample (1 click / 2 impressions).
    ctr_smoothing_virtual_impressions: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
