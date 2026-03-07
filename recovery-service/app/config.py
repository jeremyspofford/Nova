import os
from pathlib import Path


class Settings:
    port: int = 8888
    backup_dir: Path = Path(os.getenv("BACKUP_DIR", "/backups"))
    backup_retain_days: int = int(os.getenv("BACKUP_RETAIN_DAYS", "30"))

    # Postgres — direct connection (no ORM, no SQLAlchemy)
    pg_host: str = os.getenv("POSTGRES_HOST", "postgres")
    pg_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    pg_user: str = os.getenv("POSTGRES_USER", "nova")
    pg_password: str = os.getenv("POSTGRES_PASSWORD", "nova_dev_password")
    pg_database: str = os.getenv("POSTGRES_DB", "nova")

    # Admin auth
    admin_secret: str = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")

    # Automatic checkpoints
    checkpoint_interval_hours: int = int(os.getenv("CHECKPOINT_INTERVAL_HOURS", "6"))
    checkpoint_max_keep: int = int(os.getenv("CHECKPOINT_MAX_KEEP", "5"))

    @property
    def pg_dsn(self) -> str:
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"


settings = Settings()
