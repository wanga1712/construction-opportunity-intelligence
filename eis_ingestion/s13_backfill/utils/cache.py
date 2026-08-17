"""
Простое кэширование для часто используемых запросов к БД.
"""
from typing import Optional, Dict, Any
import time


class SimpleCache:
    """Простой кэш с TTL (Time To Live)."""
    
    # Специальный объект для обозначения "не найдено"
    NOT_FOUND = object()
    
    def __init__(self, ttl: int = 3600):
        """
        Инициализация кэша.
        
        :param ttl: Время жизни кэша в секундах (по умолчанию 1 час)
        """
        self.cache: Dict[str, tuple[Any, float]] = {}
        self.ttl = ttl
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Получить значение из кэша.
        
        :param key: Ключ кэша
        :param default: Значение по умолчанию, если ключ не найден
        :return: Значение из кэша или default
        """
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                # Если это маркер "не найдено", возвращаем None
                if value is self.NOT_FOUND:
                    return None
                return value
            else:
                # Удаляем устаревшее значение
                del self.cache[key]
        return default
    
    def has(self, key: str) -> bool:
        """
        Проверить наличие ключа в кэше (и что он не устарел).
        
        :param key: Ключ кэша
        :return: True, если ключ существует и не устарел
        """
        if key in self.cache:
            _, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return True
            else:
                del self.cache[key]
        return False
    
    def set(self, key: str, value: Any):
        """
        Установить значение в кэш.
        Если value is None, сохраняется специальный маркер.
        
        :param key: Ключ кэша
        :param value: Значение для кэширования (может быть None)
        """
        # Если значение None, сохраняем специальный маркер
        cache_value = self.NOT_FOUND if value is None else value
        self.cache[key] = (cache_value, time.time())
    
    def clear(self):
        """Очистить кэш."""
        self.cache.clear()
    
    def invalidate(self, key: str):
        """
        Удалить значение из кэша.
        
        :param key: Ключ кэша
        """
        if key in self.cache:
            del self.cache[key]


# Глобальный экземпляр кэша
_global_cache = SimpleCache(ttl=3600)


def get_cache() -> SimpleCache:
    """Получить глобальный экземпляр кэша."""
    return _global_cache


def clear_cache():
    """Очистить глобальный кэш."""
    _global_cache.clear()

