from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Transmission RPC
    transmission_host: str = "127.0.0.1"
    transmission_port: int = 9191
    transmission_rpc_username: str = "admin"
    transmission_rpc_password: str = "adminadmin"

    # SearXNG
    searxng_host: str = "http://127.0.0.1:8080"

    # Paths
    download_dir: str = "/downloads"
    cache_db_path: str = "/app/data/cache.db"
    rom_dir: str = "/data/roms"

    # Server
    flask_port: int = 8180

    # Auth
    auth_user: str = ""
    auth_pass: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_admin_id: int = 5597932516

    # Token
    token_expiry_days: int = 7

    # Public URL
    app_url: str = "http://localhost:8180"

    # OpenVPN (for transmission container)
    openvpn_provider: str = "PUREVPN"
    openvpn_username: str = ""
    openvpn_password: str = ""
    openvpn_config: str = "nl2-auto-tcp-qr"

    # Dynu DNS (for Traefik)
    dynu_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
