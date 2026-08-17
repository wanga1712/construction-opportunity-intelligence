"""
MODULE: config.settings
RESPONSIBILITY: Application configuration loading and validation.
ALLOWED: os, dotenv, dataclasses.
FORBIDDEN: Complex business logic, database connections (only config).
ERRORS: ValueError (validation).
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import os
from pathlib import Path
from dotenv import load_dotenv
import logging
from loguru import logger


@dataclass(frozen=True)
class DatabaseConfig:
    """Конфигурация базы данных"""
    host: str
    database: str
    user: str
    password: str
    port: int

    def get_connection_string(self) -> str:
        """Получить строку подключения для psycopg2"""
        return f"host={self.host} dbname={self.database} user={self.user} password={self.password} port={self.port}"


@dataclass(frozen=True)
class DeliveryConfig:
    """Конфигурация доставки"""
    cost_per_km: float
    manipulator_base_cost: float
    rear_loader_base_cost: float
    side_loader_base_cost: float
    gazelle_capacity: int


@dataclass(frozen=True)
class UIConfig:
    """Конфигурация пользовательского интерфейса"""
    window_size: str
    background_color: str
    accent_color: str
    font_family: str
    font_size: int


@dataclass(frozen=True)
class AppConfig:
    """Основная конфигурация приложения"""
    app_name: str
    app_version: str
    log_level: str
    log_rotation: str
    log_retention: str


@dataclass(frozen=True)
class OpenRouterConfig:
    """Конфигурация OpenRouter AI API"""
    api_key: Optional[str]
    api_url: str = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class YandexDiskConfig:
    """Конфигурация Яндекс Диска"""
    token: Optional[str]
    enabled: bool = False
    base_path: str = "/tender_documents"
    upload_after_download: bool = True


class Config:
    """
    Главный класс конфигурации, загружающий все настройки из .env файла
    """

    def __init__(self, env_file: Optional[str] = None):
        """
        Инициализация конфигурации

        Args:
            env_file: Путь к .env файлу (опционально)
        """
        self._load_environment(env_file)
        self.database = self._load_database_config()
        self.tender_database = self._load_tender_database_config()
        self.delivery = self._load_delivery_config()
        self.ui = self._load_ui_config()
        self.app = self._load_app_config()
        self.openrouter = self._load_openrouter_config()
        self.yandex_disk = self._load_yandex_disk_config()
        # Пути к инструментам и директориям (настраиваются через .env)
        # По умолчанию используется домашняя директория пользователя
        default_download_dir = str(Path.home() / "Downloads" / "ЕИС_Документация")
        self.unrar_tool = self._get_env_var("UNRAR_TOOL", None)
        self.document_download_dir = self._get_env_var("DOCUMENT_DOWNLOAD_DIR", default_download_dir)
        self.winrar_path = self._get_env_var("WINRAR_PATH", None)
        # Директория для документов по командировкам (чеки, отчеты)
        self.business_trip_docs_dir = self._get_env_var("BUSINESS_TRIP_DOCS_DIR", None)
        # Конфигурация базы знаний (Яндекс.Диск)
        self.knowledge_base_root = self._get_env_var(
            "KNOWLEDGE_BASE_ROOT", 
            r"C:\Users\wangr\YandexDisk\Обмен информацией\Отдел продаж\CRM"
        )

        self._configure_external_tools()
        # Конфигурация загружена успешно (без лога для уменьшения шума)

    def _load_environment(self, env_file: Optional[str]) -> None:
        """Загрузка переменных окружения"""
        try:
            if env_file and os.path.exists(env_file):
                load_dotenv(env_file)
            else:
                load_dotenv()
        except Exception as e:
            logger.warning(f"Не удалось загрузить .env файл: {e}")

    def _get_env_var(self, key: str, default: Any = None, required: bool = False) -> str:
        """
        Получение переменной окружения с валидацией

        Args:
            key: Ключ переменной
            default: Значение по умолчанию
            required: Обязательная ли переменная

        Returns:
            Значение переменной

        Raises:
            ValueError: Если обязательная переменная не найдена
        """
        value = os.getenv(key)

        if value is None:
            if required:
                raise ValueError(f"Обязательная переменная окружения {key} не найдена")
            return default

        return value

    def _get_env_float(self, key: str, default: float = 0.0) -> float:
        """Получение float переменной из окружения"""
        try:
            return float(self._get_env_var(key, default))
        except (TypeError, ValueError) as e:
            logger.warning(f"Неверный формат float для {key}: {e}, используется значение по умолчанию: {default}")
            return default

    def _get_env_int(self, key: str, default: int = 0) -> int:
        """Получение int переменной из окружения"""
        try:
            return int(self._get_env_var(key, default))
        except (TypeError, ValueError) as e:
            logger.warning(f"Неверный формат int для {key}: {e}, используется значение по умолчанию: {default}")
            return default

    def _configure_external_tools(self) -> None:
        """Настройка путей для WinRAR/UnRAR в системных переменных."""
        if self.winrar_path:
            winrar_dir = Path(self.winrar_path)
            if winrar_dir.exists():
                current_path = os.environ.get("PATH", "")
                path_parts = current_path.split(os.pathsep) if current_path else []
                if str(winrar_dir) not in path_parts:
                    os.environ["PATH"] = os.pathsep.join(path_parts + [str(winrar_dir)]) if path_parts else str(winrar_dir)
        if self.unrar_tool:
            os.environ.setdefault("UNRAR_TOOL", self.unrar_tool)

    def _get_env_bool(self, key: str, default: bool = False) -> bool:
        """Получение bool переменной из окружения"""
        value = self._get_env_var(key, default)
        if isinstance(value, bool):
            return value
        return value.lower() in ('true', '1', 'yes', 'y')

    def _load_database_config(self) -> DatabaseConfig:
        """Загрузка конфигурации базы данных (каталог продукции)"""
        return DatabaseConfig(
            host=self._get_env_var("DB_HOST", "localhost"),
            database=self._get_env_var("DB_DATABASE", "commercial_db", required=True),
            user=self._get_env_var("DB_USER", "postgres", required=True),
            password=self._get_env_var("DB_PASSWORD", "", required=True),
            port=self._get_env_int("DB_PORT", 5432)
        )
    
    def _load_tender_database_config(self) -> DatabaseConfig:
        """Загрузка конфигурации базы данных tender_monitor"""
        host = self._get_env_var("TENDER_MONITOR_DB_HOST", required=True)
        database = self._get_env_var("TENDER_MONITOR_DB_DATABASE", required=True)
        user = self._get_env_var("TENDER_MONITOR_DB_USER", required=True)
        password = self._get_env_var("TENDER_MONITOR_DB_PASSWORD", required=True)
        port = self._get_env_int("TENDER_MONITOR_DB_PORT", 5432)
        
        return DatabaseConfig(
            host=host,
            database=database,
            user=user,
            password=password,
            port=port
        )

    def _load_delivery_config(self) -> DeliveryConfig:
        """Загрузка конфигурации доставки"""
        return DeliveryConfig(
            cost_per_km=self._get_env_float("DELIVERY_COST_PER_KM", 15.0),
            manipulator_base_cost=self._get_env_float("DELIVERY_MANIPULATOR_COST", 5000.0),
            rear_loader_base_cost=self._get_env_float("DELIVERY_REAR_LOADER_COST", 3000.0),
            side_loader_base_cost=self._get_env_float("DELIVERY_SIDE_LOADER_COST", 4000.0),
            gazelle_capacity=self._get_env_int("DELIVERY_GAZELLE_CAPACITY", 50)
        )

    def _load_ui_config(self) -> UIConfig:
        """Загрузка конфигурации интерфейса"""
        return UIConfig(
            window_size=self._get_env_var("UI_WINDOW_SIZE", "1200x800"),
            background_color=self._get_env_var("UI_BACKGROUND_COLOR", "#F5F5F5"),  # Bitrix24 Light Gray Background
            accent_color=self._get_env_var("UI_ACCENT_COLOR", "#2066B0"),  # Bitrix24 Primary Blue
            font_family=self._get_env_var("UI_FONT_FAMILY", "Arial"),
            font_size=self._get_env_int("UI_FONT_SIZE", 16)  # Умеренно увеличен базовый размер шрифта
        )

    def _load_app_config(self) -> AppConfig:
        """Загрузка основной конфигурации приложения"""
        return AppConfig(
            app_name=self._get_env_var("APP_NAME", "Коммерческое приложение"),
            app_version=self._get_env_var("APP_VERSION", "1.0.0"),
            log_level=self._get_env_var("LOG_LEVEL", "INFO"),
            log_rotation=self._get_env_var("LOG_ROTATION", "10 MB"),
            log_retention=self._get_env_var("LOG_RETENTION", "30 days")
        )

    def _load_openrouter_config(self) -> OpenRouterConfig:
        """Загрузка конфигурации OpenRouter AI API"""
        return OpenRouterConfig(
            api_key=self._get_env_var("OPENROUTER_API_KEY", None),
            api_url=self._get_env_var("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
        )

    def _load_yandex_disk_config(self) -> YandexDiskConfig:
        """Загрузка конфигурации Яндекс Диска"""
        token = self._get_env_var("YANDEX_DISK_TOKEN", None)
        enabled = self._get_env_bool("YANDEX_DISK_ENABLED", False) if token else False
        return YandexDiskConfig(
            token=token,
            enabled=enabled,
            base_path=self._get_env_var("YANDEX_DISK_BASE_PATH", "/tender_documents"),
            upload_after_download=self._get_env_bool("YANDEX_DISK_UPLOAD_AFTER_DOWNLOAD", True)
        )

    def validate(self) -> bool:
        """
        Валидация конфигурации

        Returns:
            True если конфигурация валидна
        """
        try:
            # Проверка обязательных полей БД
            if not all([self.database.database, self.database.user, self.database.password]):
                raise ValueError("Не все обязательные параметры БД заполнены")

            # Проверка положительных значений доставки
            delivery_fields = [
                self.delivery.cost_per_km,
                self.delivery.manipulator_base_cost,
                self.delivery.rear_loader_base_cost,
                self.delivery.side_loader_base_cost,
                self.delivery.gazelle_capacity
            ]

            if any(value <= 0 for value in delivery_fields):
                raise ValueError("Все стоимости доставки должны быть положительными")

            logger.info("Конфигурация прошла валидацию")
            return True

        except Exception as e:
            logger.error(f"Ошибка валидации конфигурации: {e}")
            return False

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование конфигурации в словарь (без паролей)"""
        return {
            "database": {
                "host": self.database.host,
                "database": self.database.database,
                "user": self.database.user,
                "port": self.database.port
            },
            "delivery": {
                "cost_per_km": self.delivery.cost_per_km,
                "manipulator_base_cost": self.delivery.manipulator_base_cost,
                "rear_loader_base_cost": self.delivery.rear_loader_base_cost,
                "side_loader_base_cost": self.delivery.side_loader_base_cost,
                "gazelle_capacity": self.delivery.gazelle_capacity
            },
            "ui": {
                "window_size": self.ui.window_size,
                "background_color": self.ui.background_color,
                "accent_color": self.ui.accent_color,
                "font_family": self.ui.font_family,
                "font_size": self.ui.font_size
            },
            "app": {
                "app_name": self.app.app_name,
                "app_version": self.app.app_version,
                "log_level": self.app.log_level
            },
            "unrar_tool": self.unrar_tool,
        }


# Создание глобального экземпляра конфигурации
try:
    config = Config()
except Exception as e:
    print(f"CRITICAL ERROR during config initialization: {e}", file=__import__('sys').stderr)
    __import__('sys').exit(1)