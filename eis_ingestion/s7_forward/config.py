"""
MODULE: config
RESPONSIBILITY: Facade for configuration management. Exposes Settings from config package.
ALLOWED: importing from config.settings.
FORBIDDEN: defining configuration logic here (keep in config.settings).
ERRORS: ConfigError.

Точка входа для конфигурации.
Перенаправляет на config.settings.Settings для совместимости.
В будущем можно перенести логику сюда полностью.
"""
from config.settings import Settings

# Создаем глобальный экземпляр настроек
settings = Settings()

__all__ = ["settings", "Settings"]
