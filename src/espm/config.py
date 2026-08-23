from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class EspmEnvironment(StrEnum):
    TEST = "test"
    LIVE = "live"

    @property
    def base_url(self) -> str:
        if self is EspmEnvironment.TEST:
            return "https://portfoliomanager.energystar.gov/wstest"
        return "https://portfoliomanager.energystar.gov/ws"


class EspmConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    username: str = Field(min_length=1)
    password: SecretStr
    environment: EspmEnvironment = EspmEnvironment.TEST
    base_url: str | None = None
    connect_timeout: float = Field(default=10.0, gt=0)
    read_timeout: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    user_agent: str = "espm-python/0.1.0"
    allow_mutations: bool = False

    @property
    def resolved_base_url(self) -> str:
        return (self.base_url or self.environment.base_url).rstrip("/")
