import os
import zipfile

from utils.logger_config import get_logger
from secondary_functions import load_config

logger = get_logger()


class ArchiveExtractor:
    def __init__(self, config_path="config.ini"):
        self.config = load_config(config_path)
        if not self.config:
            raise ValueError("Ошибка загрузки конфигурации!")

    def unzip_files(self, directory):
        zip_files = [f for f in os.listdir(directory) if f.endswith('.zip')]
        
        if not zip_files:
            return
        
        for file_name in zip_files:
            zip_path = os.path.join(directory, file_name)
            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(directory)
                    
            except zipfile.BadZipFile:
                error_msg = f"Не удалось разархивировать файл (неверный формат ZIP): {zip_path}"
                logger.error(error_msg)
            except Exception as e:
                error_msg = f"Ошибка при разархивировании файла {zip_path}: {e}"
                logger.error(error_msg, exc_info=True)

