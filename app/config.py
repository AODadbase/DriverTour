from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量 / .env 读取配置，字段名大小写不敏感（MAPBOX_ACCESS_TOKEN 等）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mapbox_access_token: str = ""
    mapbox_base_url: str = "https://api.mapbox.com/search/searchbox/v1"
    # Search Box category search 必须指定分类；未传 category 时使用此默认值
    default_poi_category: str = "restaurant"
    poi_limit: int = 10  # Mapbox 单次最多 25
    http_timeout_s: float = 10.0

    # /tracks/{id}/pois 单次请求最多触发的 Mapbox 调用数，防止烧光免费额度
    max_poi_queries_per_track: int = 20
    poi_query_concurrency: int = 3

    sample_gpx_path: str = "data/sample.gpx"


@lru_cache
def get_settings() -> Settings:
    return Settings()
