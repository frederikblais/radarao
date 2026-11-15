"""Configuration centrale lue depuis les variables d'environnement (voir .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://radarao:radarao@localhost:5432/radarao"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "dev-only-change-me"
    web_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Stockage S3 (MinIO en local)
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_bucket: str = "radarao-documents"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "ca-central-1"
    storage_backend: str = "s3"  # "s3" ou "local" (tests, développement sans MinIO)
    local_storage_dir: str = "/tmp/radarao-storage"

    # Fournisseurs d'IA (clés côté serveur seulement)
    anthropic_api_key: str | None = None
    voyage_api_key: str | None = None
    # "live" = vrais appels; "offline" = embeddings déterministes locaux (dev/tests), LLM refusé
    ai_mode: str = "live"

    # Budgets (USD)
    budget_per_dossier_usd: float = 5.0
    budget_monthly_company_usd: float = 50.0

    # Téléversements
    max_upload_mb: int = 64
    retention_days: int = 90

    # Courriels
    email_backend: str = "console"  # "console" ou "smtp"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "RadarAO <alertes@radarao.local>"

    # Authentification Google (optionnelle)
    google_client_id: str | None = None
    google_client_secret: str | None = None

    # SEAO
    seao_dataset_id: str = "systeme-electronique-dappel-doffres-seao"
    ckan_api_url: str = "https://www.donneesquebec.ca/recherche/api/3/action"

    # "celery" (production), "inline" (dev sans Redis : exécution immédiate), "none" (tests)
    task_mode: str = "celery"

    # Databricks (lakehouse analytique, en tandem avec PostgreSQL — ADR-005)
    databricks_host: str | None = None  # ex. dbc-xxxx.cloud.databricks.com
    databricks_token: str | None = None
    databricks_warehouse_id: str | None = None
    databricks_catalog: str = "workspace"
    databricks_schema: str = "radarao"
    databricks_volume: str = "seao_raw"

    # Limites de débit (requêtes par heure et par utilisateur)
    rate_limit_analyze_per_hour: int = 10
    rate_limit_chat_per_hour: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
