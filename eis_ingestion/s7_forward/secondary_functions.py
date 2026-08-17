import json
import configparser
import os
from dotenv import load_dotenv
import inspect
from typing import Optional

from utils.logger_config import get_logger
from utils.config_manager import ConfigManager
from utils.exceptions import ConfigurationError

# Получаем logger (только ошибки в файл)
logger = get_logger()

# Глобальный экземпляр менеджера конфигурации
_config_manager: Optional[ConfigManager] = None


def load_config(config_path="config.ini"):
    """
    Загружает конфигурационный файл и возвращает объект ConfigParser.
    Использует кэшированный экземпляр ConfigManager для производительности.

    :param config_path: Путь к конфигурационному файлу (по умолчанию "config.ini").
    :return: Объект ConfigParser с загруженной конфигурацией.
    :raises ConfigurationError: Если не удалось загрузить конфигурацию.
    """
    global _config_manager
    
    # Используем кэшированный экземпляр, если он уже создан
    if _config_manager is None or _config_manager.config_path != config_path:
        try:
            _config_manager = ConfigManager(config_path)
            # Валидация конфигурации
            if not _config_manager.validate():
                raise ConfigurationError("Конфигурация не прошла валидацию")
        except ConfigurationError:
            raise
        except Exception as e:
            error_msg = f"Ошибка загрузки конфигурации: {e}"
            logger.error(error_msg, exc_info=True)
            raise ConfigurationError(error_msg) from e
    
    return _config_manager.config


def check_file_exists(file_path, description):
    """
    Проверяет существование файла и логирует ошибку, если его нет.

    :param file_path: Путь к проверяемому файлу.
    :param description: Описание файла для вывода в лог.
    :return: True, если файл существует, иначе False.
    """
    if not os.path.exists(file_path):
        logger.error(f"Файл {description} не найден: {file_path}")
        return False
    return True


def load_regions(regions_file):
    """
    Загружает словарь регионов из JSON-файла.

    :param regions_file: Путь к файлу с регионами.
    :return: Словарь регионов или пустой словарь в случае ошибки.
    """
    # Проверяем, существует ли файл с регионами
    if not check_file_exists(regions_file, "регионов"):
        return {}

    try:
        # Загружаем регионы из JSON-файла
        with open(regions_file, "r", encoding="utf-8") as file:
            regions = json.load(file)
            return regions
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка в JSON-файле {regions_file}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Неизвестная ошибка при загрузке регионов: {e}", exc_info=True)

    return {}


def get_region_codes(regions_file):
    """
    Возвращает список кодов регионов.

    :param regions_file: Путь к файлу с регионами.
    :return: Список кодов регионов.
    """
    regions = load_regions(regions_file)
    # Если регионы загружены, возвращаем список кодов, иначе пустой список
    return [int(code) for code in regions.keys()] if regions else []


def load_token(config):
    """
    Загружает токен из .env файла, путь к которому хранится в config.ini.

    :param config: Объект конфигурации, в котором хранится путь к .env файлу.
    :return: Токен из .env файла или None, если токен не найден.
    """
    # Получаем путь к .env файлу из конфигурации
    env_path = config.get("path", "env_file", fallback=None)

    if not env_path:
        logger.error("Путь к .env файлу не найден в config.ini")
        return None

    env_path = os.path.normpath(env_path)  # Приводим путь к корректному формату

    # Проверяем существование .env файла
    if not check_file_exists(env_path, ".env"):
        return None

    # Загружаем .env файл
    load_dotenv(env_path)
    token = os.getenv("TOKEN")

    if not token:
        logger.error(f"Токен не найден в .env файле: {env_path}")

    return token


# --- Основной блок кода ---
if __name__ == "__main__":
    config = load_config()
    token = load_token(config)
    
    if not token:
        print("❌ Ошибка: Токен не найден!")
    else:
        print("✅ Токен загружен успешно")