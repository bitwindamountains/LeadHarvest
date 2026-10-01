"""Settings. The only module that reads environment variables (blueprint section 11)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """A missing or invalid setting. The CLI prints the message and exits with code 2."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    user_agent: str = ""

    db_path: Path = Path("data/leads.db")
    export_dir: Path = Path("data/exports")
    log_dir: Path = Path("data/logs")
    categories_file: Path | None = None

    concurrency: int = Field(default=5, ge=1, le=20)
    per_domain_delay_seconds: float = Field(default=2.0, ge=1.0)
    request_timeout_seconds: float = Field(default=15.0, gt=0)
    max_response_bytes: int = Field(default=2_000_000, gt=0)
    max_extra_pages: int = Field(default=2, ge=0, le=5)
    default_region: str = "PH"

    phone_match_radius_m: float = Field(default=250.0, gt=0)
    shared_phone_min_names: int = Field(default=3, ge=2)

    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    overpass_urls: str = (
        "https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter"
    )

    google_service_account_file: Path = Field(
        default=Path("secrets/service_account.json"), alias="GOOGLE_SERVICE_ACCOUNT_FILE"
    )
    google_sheet_id: str = Field(default="", alias="GOOGLE_SHEET_ID")

    mx_check: bool = True  # V1: drop emails on domains that cannot receive mail
    hubspot_access_token: str = Field(default="", alias="HUBSPOT_ACCESS_TOKEN", repr=False)
    ui_password: str = Field(default="", repr=False)

    @field_validator("default_region")
    @classmethod
    def _upper_region(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def overpass_url_list(self) -> list[str]:
        return [u.strip() for u in self.overpass_urls.split(",") if u.strip()]

    @property
    def ua_product(self) -> str:
        """Product token used to match robots.txt groups, e.g. 'LeadHarvest'."""
        token = self.user_agent.strip().split("/", 1)[0].split(" ", 1)[0]
        return token or "LeadHarvest"

    def require_network_identity(self) -> None:
        """Politeness rule: refuse to make requests without an honest, contactable User-Agent."""
        ua = self.user_agent.strip()
        if not ua:
            raise ConfigError("LH_USER_AGENT is not set. Copy .env.example to .env and edit it.")
        if "example.com" in ua.lower():
            raise ConfigError(
                "LH_USER_AGENT still contains the example.com placeholder. "
                "Put your real contact email or URL in .env."
            )
        if not any(marker in ua for marker in ("mailto:", "@", "http")):
            raise ConfigError("LH_USER_AGENT must include a contact (mailto:, email, or URL).")

    def require_hubspot(self) -> None:
        if not self.hubspot_access_token:
            raise ConfigError(
                "--to hubspot needs HUBSPOT_ACCESS_TOKEN (a HubSpot private app token)."
            )

    def require_sheets(self) -> None:
        if not self.google_sheet_id:
            raise ConfigError("--to sheets needs GOOGLE_SHEET_ID in .env.")
        if not self.google_service_account_file.is_file():
            raise ConfigError(
                f"Service account file not found: {self.google_service_account_file}. "
                "See README 'Google Sheets setup'."
            )


def load_settings(**overrides: object) -> Settings:
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'settings'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ConfigError(f"Invalid configuration: {problems}") from None
