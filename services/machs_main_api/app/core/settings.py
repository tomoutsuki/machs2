import os
from dataclasses import dataclass


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_host: str = os.getenv("MAIN_API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("MAIN_API_PORT", "8000"))
    log_level: str = os.getenv("MAIN_API_LOG_LEVEL", "info")

    jwt_secret: str = os.getenv("MAIN_API_JWT_SECRET", "change_me_jwt_secret")
    jwt_algorithm: str = os.getenv("MAIN_API_JWT_ALGORITHM", "HS256")
    jwt_exp_minutes: int = int(os.getenv("MAIN_API_JWT_EXP_MINUTES", "120"))

    cookie_name: str = os.getenv("MAIN_API_COOKIE_NAME", "machs2_session")
    cookie_secure: bool = _as_bool(os.getenv("MAIN_API_COOKIE_SECURE", "false"))
    cookie_samesite: str = os.getenv("MAIN_API_COOKIE_SAMESITE", "lax")
    allow_origins: str = os.getenv("MAIN_API_ALLOW_ORIGINS", "http://localhost:8000")

    reset_on_start: bool = _as_bool(os.getenv("MAIN_API_RESET_ON_START", "true"), True)
    enable_experimental_revocation: bool = _as_bool(
        os.getenv("MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION", "false"), False
    )
    current_epoch: str = os.getenv("MAIN_API_CURRENT_EPOCH", "epoch.2026")
    policy_strict: bool = _as_bool(os.getenv("MAIN_API_POLICY_STRICT", "true"), True)

    postgres_db: str = os.getenv("POSTGRES_DB", "machs2")
    postgres_user: str = os.getenv("POSTGRES_USER", "machs2")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "machs2_dev_password")
    postgres_host: str = os.getenv("POSTGRES_HOST", "machs_postgresql")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))

    kms_host: str = os.getenv("KMS_HOST", "machs_minimal_kms")
    kms_port: int = int(os.getenv("KMS_PORT", "8100"))
    kms_internal_token: str = os.getenv("KMS_INTERNAL_TOKEN", "change_me_internal_token")

    fabeo_host: str = os.getenv("FABEO_HOST", "machs_fabeo_service")
    fabeo_port: int = int(os.getenv("FABEO_PORT", "8200"))
    fabeo_mode: str = os.getenv("FABEO_MODE", "fabeo22cp")

    bcrypt_rounds: int = int(os.getenv("BCRYPT_ROUNDS", "12"))

    @property
    def database_dsn(self) -> str:
        return (
            "dbname={db} user={user} password={pwd} host={host} port={port}"
        ).format(
            db=self.postgres_db,
            user=self.postgres_user,
            pwd=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
        )

    @property
    def kms_url(self) -> str:
        return "http://{0}:{1}".format(self.kms_host, self.kms_port)

    @property
    def fabeo_url(self) -> str:
        return "http://{0}:{1}".format(self.fabeo_host, self.fabeo_port)


settings = Settings()
