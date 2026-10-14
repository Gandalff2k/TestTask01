import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DRIVE_FOLDER_ID = "1b_hEjnkQfP8ZVP-OEbnYWqoGSFwXMAP3"


@dataclass(frozen=True)
class Settings:
    bot_token: str
    groq_api_key: str
    groq_model: str
    drive_folder_id: str
    drive_sync_minutes: int
    data_dir: Path
    timezone: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.sqlite3"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задано змінну оточення {name} (див. .env.example)")
    return value


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token=_required("BOT_TOKEN"),
        groq_api_key=_required("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        drive_folder_id=os.getenv("DRIVE_FOLDER_ID", DEFAULT_DRIVE_FOLDER_ID),
        drive_sync_minutes=int(os.getenv("DRIVE_SYNC_MINUTES", "30")),
        data_dir=data_dir,
        timezone=os.getenv("TZ_NAME", "Europe/Kyiv"),
    )
