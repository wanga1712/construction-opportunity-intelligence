"""
Кастомные исключения для проекта TenderMonitor.
"""
from typing import Optional


class TenderMonitorError(Exception):
    """Базовое исключение для проекта TenderMonitor."""
    pass


class DatabaseError(TenderMonitorError):
    """Ошибка при работе с базой данных."""
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


class ConfigurationError(TenderMonitorError):
    """Ошибка конфигурации."""
    pass


class EISRequestError(TenderMonitorError):
    """Ошибка при запросе к ЕИС."""
    def __init__(self, message: str, region_code: Optional[int] = None, 
                 subsystem: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.region_code = region_code
        self.subsystem = subsystem
        self.status_code = status_code


class FileProcessingError(TenderMonitorError):
    """Ошибка при обработке файла."""
    def __init__(self, message: str, file_path: Optional[str] = None):
        super().__init__(message)
        self.file_path = file_path


class XMLParsingError(TenderMonitorError):
    """Ошибка при парсинге XML."""
    def __init__(self, message: str, file_path: Optional[str] = None):
        super().__init__(message)
        self.file_path = file_path


# Обратная совместимость с прежними именами исключений
class NetworkError(EISRequestError):
    """Алиас для EISRequestError (обратная совместимость)."""
    pass


class FileOperationError(FileProcessingError):
    """Алиас для FileProcessingError (обратная совместимость)."""
    pass


class ParsingError(XMLParsingError):
    """Алиас для XMLParsingError (обратная совместимость)."""
    pass