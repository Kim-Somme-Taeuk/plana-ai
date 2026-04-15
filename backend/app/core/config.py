from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    POSTGRES_USER: str = "plana"
    POSTGRES_PASSWORD: str = "plana"
    POSTGRES_DB: str = "plana_ai"
    POSTGRES_PORT: int = 5432
    POSTGRES_HOST: str = "db"

    model_config = SettingsConfigDict(
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
