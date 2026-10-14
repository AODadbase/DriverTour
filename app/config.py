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

    # Week 2：LLM（DeepSeek）
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    llm_temperature: float = 0.0
    llm_timeout_s: float = 60.0

    # Week 2：Wikipedia 要求描述性的 User-Agent，否则可能被拒绝
    wikipedia_user_agent: str = "DriverTour/0.2 (student project; https://github.com/)"
    # run_tour 查询的"地标类" Mapbox 分类，逗号分隔
    landmark_categories: str = "museum,park,monument,historic_site,place_of_worship,university,theatre"


@lru_cache
def get_settings() -> Settings:
    return Settings()
