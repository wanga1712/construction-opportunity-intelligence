"""
Централизованное управление конфигурацией проекта.
"""
import os
import configparser
from typing import Optional, Dict, Any
from pathlib import Path

from utils.logger_config import get_logger
from utils.exceptions import ConfigurationError

logger = get_logger()


class ConfigManager:
    """Централизованный менеджер конфигурации."""
    
    def __init__(self, config_path: str = "config.ini"):
        """
        Инициализация менеджера конфигурации.
        
        :param config_path: Путь к файлу конфигурации
        :raises ConfigurationError: Если не удалось загрузить конфигурацию
        """
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self._load_config()
    
    def _load_config(self):
        """Загружает конфигурацию из файла."""
        try:
            # Определяем путь относительно корня проекта
            if not os.path.isabs(self.config_path):
                # Получаем путь к корню проекта
                project_root = Path(__file__).parent.parent
                config_full_path = project_root / self.config_path
            else:
                config_full_path = Path(self.config_path)
            
            if not config_full_path.exists():
                raise ConfigurationError(f"Файл конфигурации не найден: {config_full_path}")
            
            self.config.read(config_full_path, encoding="utf-8")
        except configparser.Error as e:
            error_msg = f"Ошибка при загрузке конфигурации: {e}"
            logger.error(error_msg, exc_info=True)
            raise ConfigurationError(error_msg) from e
        except Exception as e:
            error_msg = f"Неожиданная ошибка при загрузке конфигурации: {e}"
            logger.error(error_msg, exc_info=True)
            raise ConfigurationError(error_msg) from e
    
    def get(self, section: str, option: str, fallback: Optional[str] = None) -> str:
        """
        Получить значение из конфигурации.
        
        :param section: Секция конфигурации
        :param option: Опция в секции
        :param fallback: Значение по умолчанию
        :return: Значение из конфигурации
        :raises ConfigurationError: Если секция или опция не найдены и fallback не указан
        """
        try:
            return self.config.get(section, option, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError) as e:
            if fallback is not None:
                return fallback
            error_msg = f"Конфигурация не найдена: секция '{section}', опция '{option}'"
            logger.error(error_msg)
            raise ConfigurationError(error_msg) from e
    
    def get_section(self, section: str) -> Dict[str, str]:
        """
        Получить всю секцию конфигурации.
        
        :param section: Имя секции
        :return: Словарь с опциями секции
        :raises ConfigurationError: Если секция не найдена
        """
        if not self.config.has_section(section):
            raise ConfigurationError(f"Секция конфигурации не найдена: '{section}'")
        
        return dict(self.config[section])
    
    def get_list(self, section: str, option: str, separator: str = ",") -> list:
        """
        Получить список значений из конфигурации.
        
        :param section: Секция конфигурации
        :param option: Опция в секции
        :param separator: Разделитель значений
        :return: Список значений
        """
        value = self.get(section, option, fallback="")
        return [item.strip() for item in value.split(separator) if item.strip()]
    
    def validate(self) -> bool:
        """
        Валидация конфигурации.
        
        :return: True, если конфигурация валидна
        """
        required_sections = ['stunnel', 'path', 'eis', 'tags']
        for section in required_sections:
            if not self.config.has_section(section):
                logger.error(f"Отсутствует обязательная секция конфигурации: '{section}'")
                return False
        return True

