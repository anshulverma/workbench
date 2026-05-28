# server/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    storage_backend: str = "sqlite"
    sqlite_path: str = "/data/workbench.db"
    api_token: str = "dev-token-change-me"
    port: int = 8421
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://plugboard.x2p.facebook.net"
    zep_url: str = ""
    gchat_space_id: str = ""
    google_api_script: str = "server/lib/google_api.py"
    poll_interval_minutes: int = 15
    triage_timeout_minutes: int = 30
    morning_briefing_hour: int = 9
    debug: bool = False

    class Config:
        env_prefix = "WORKBENCH_"
