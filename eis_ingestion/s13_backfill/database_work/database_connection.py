import os
import psycopg2
import threading
from dotenv import load_dotenv
from contextlib import contextmanager
from typing import Optional, Dict

from utils.logger_config import get_logger
from utils.exceptions import DatabaseError

import time

logger = get_logger()


class DatabaseManager:
    """
    Класс для управления подключением и взаимодействием с базой данных.

    Поддерживает как одиночное подключение по умолчанию, так и набор
    подключений по алиасам (например, tender_monitor, product_catalog_2).
    """

    def __init__(self, db_configs: Optional[Dict[str, Dict[str, Optional[str]]]] = None):
        """
        Инициализация объекта DatabaseManager.

        Если db_configs не передан, настройки берутся из db_credintials.env
        для базы tender_monitor.
        """
        env_file_path = os.path.join(os.path.dirname(__file__), "db_credintials.env")
        load_dotenv(dotenv_path=env_file_path)

        self.connections: Dict[str, psycopg2.extensions.connection] = {}
        self.cursors: Dict[str, psycopg2.extensions.cursor] = {}
        self.default_alias = "tender_monitor"
        self.lock = threading.RLock()

        # Save db_configs for reconnection
        self.db_configs = db_configs
        if self.db_configs is None:
            self.db_configs = {
                self.default_alias: {
                    "host": os.getenv("DB_HOST_TENDER"),
                    "name": os.getenv("DB_DATABASE_TENDER"),
                    "user": os.getenv("DB_USER_TENDER"),
                    "password": os.getenv("DB_PASSWORD_TENDER"),
                    "port": os.getenv("DB_PORT_TENDER"),
                }
            }

        # Initial connection with infinite retry if needed
        while True:
            try:
                for alias, cfg in self.db_configs.items():
                    self._create_connection(alias, cfg)
                break  # Success
            except (psycopg2.OperationalError, DatabaseError) as e:
                logger.error(f"Ошибка начального подключения к БД: {e}. Повторная попытка через 5 секунд...")
                self._close_all_connections()
                time.sleep(5)
            except Exception as e:
                logger.error(f"Критическая ошибка при подключении к БД: {e}. Повторная попытка через 5 секунд...", exc_info=True)
                self._close_all_connections()
                time.sleep(5)

        if not self.connections:
            # Should be unreachable due to while True loop above, but safety check
            logger.critical("Не удалось инициализировать ни одного подключения к БД после цикла повторов")
            raise DatabaseError("Не удалось инициализировать ни одного подключения к БД")

        if self.default_alias not in self.connections:
            self.default_alias = next(iter(self.connections.keys()))

        self.connection = self.connections[self.default_alias]
        # self.cursor removed to ensure thread safety
        
        default_cfg = self.db_configs[self.default_alias]
        self.db_host = default_cfg.get("host") or os.getenv("DB_HOST_TENDER")
        self.db_name = default_cfg.get("name") or os.getenv("DB_DATABASE_TENDER")
        self.db_user = default_cfg.get("user") or os.getenv("DB_USER_TENDER")
        self.db_password = default_cfg.get("password") or os.getenv("DB_PASSWORD_TENDER")
        self.db_port = default_cfg.get("port") or os.getenv("DB_PORT_TENDER")

    def _create_connection(self, alias: str, cfg: Dict[str, Optional[str]]):
        """Создает соединение для указанного алиаса и конфигурации."""
        if alias == self.default_alias:
            host = cfg.get("host") or os.getenv("DB_HOST_TENDER")
            name = cfg.get("name") or os.getenv("DB_DATABASE_TENDER")
            user = cfg.get("user") or os.getenv("DB_USER_TENDER")
            password = cfg.get("password") or os.getenv("DB_PASSWORD_TENDER")
            port = cfg.get("port") or os.getenv("DB_PORT_TENDER")
        elif alias == "product_catalog_2":
            host = cfg.get("host") or os.getenv("DB_HOST_CATALOG")
            name = cfg.get("name") or os.getenv("DB_DATABASE_CATALOG") or "product_catalog_2"
            user = cfg.get("user") or os.getenv("DB_USER_CATALOG")
            password = cfg.get("password") or os.getenv("DB_PASSWORD_CATALOG")
            port = cfg.get("port") or os.getenv("DB_PORT_CATALOG")
        else:
            host = cfg.get("host")
            name = cfg.get("name")
            user = cfg.get("user")
            password = cfg.get("password")
            port = cfg.get("port")

        connect_params = {
            "database": name,
            "user": user,
            "password": password,
            "host": host,
            "port": port,
            "connect_timeout": 10,
        }
        if host in ("localhost", "127.0.0.1", "<S7_DB_HOST>"):
            connect_params["sslmode"] = "disable"

        conn = psycopg2.connect(**connect_params)
        conn.autocommit = False
        
        # Try to set timeout and disable parallel workers if configured
        try:
            timeout_ms = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))
            lock_timeout_ms = int(os.getenv("DB_LOCK_TIMEOUT_MS", "10000"))
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {timeout_ms}")
                cur.execute(f"SET lock_timeout = {lock_timeout_ms}")
                cur.execute("SET max_parallel_workers_per_gather = 0")
                cur.execute("SET jit = off")
                conn.commit()
        except Exception as e:
            logger.warning(f"Не удалось настроить параметры соединения: {e}")

        self.connections[alias] = conn

    def _close_all_connections(self):
        """Закрывает все активные соединения."""
        for c in self.connections.values():
            try:
                c.close()
            except Exception:
                pass
        self.connections.clear()

    def _reconnect(self, alias: str):
        """Переподключается к базе данных по алиасу."""
        logger.info(f"Попытка переподключения к БД для алиаса '{alias}'...")
        # Закрываем старое соединение, если есть
        old_conn = self.connections.get(alias)
        if old_conn:
            try:
                old_conn.close()
            except Exception:
                pass
        
        cfg = self.db_configs.get(alias)
        if not cfg:
             # Если конфиг не найден, попробуем использовать дефолтный, если это дефолтный алиас
             if alias == self.default_alias:
                 # Reconstruct default config if missing (should not happen normally)
                 cfg = {
                    "host": os.getenv("DB_HOST_TENDER"),
                    "name": os.getenv("DB_DATABASE_TENDER"),
                    "user": os.getenv("DB_USER_TENDER"),
                    "password": os.getenv("DB_PASSWORD_TENDER"),
                    "port": os.getenv("DB_PORT_TENDER"),
                }
             else:
                 raise DatabaseError(f"Не найден конфиг для переподключения алиаса: {alias}")

        try:
            self._create_connection(alias, cfg)
            logger.info(f"Успешное переподключение к БД для алиаса '{alias}'")
            # Если это дефолтный алиас, обновляем ссылку self.connection
            if alias == self.default_alias:
                self.connection = self.connections[alias]
        except Exception as e:
            logger.error(f"Не удалось переподключиться к БД ({alias}): {e}")
            raise

    def _normalize_execute_args(self, *args):
        if not args:
            raise ValueError("execute_query: не передан SQL-запрос")

        if len(args) == 1:
            alias = self.default_alias
            query = args[0]
            params = None
        elif len(args) == 2:
            first, second = args
            if isinstance(first, str) and first in self.connections:
                alias = first
                query = second
                params = None
            else:
                alias = self.default_alias
                query = first
                params = second
        else:
            alias = args[0]
            query = args[1]
            params = args[2]
        return alias, query, params

    def execute_query(self, *args, fetch: bool = False):
        """
        Выполняет SQL-запрос.

        Поддерживаемые варианты вызова:
        - execute_query(query, params=None, fetch=False)
        - execute_query(alias, query, params=None, fetch=False)
        """
        alias, query, params = self._normalize_execute_args(*args)
        
        with self.lock:
            conn = self.connections.get(alias)
            if conn is None:
                raise DatabaseError(f"Неизвестный алиас базы данных: {alias}")
            
            max_retries = 1
            for attempt in range(max_retries + 1):
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(query, params)
                        conn.commit()
                        if fetch:
                            return cursor.fetchall()
                    return None
                except (psycopg2.InterfaceError, psycopg2.OperationalError) as e:
                    if attempt < max_retries:
                        logger.warning(
                            f"Соединение потеряно ({alias}), попытка переподключения: {e}"
                        )
                        try:
                            self._reconnect(alias)
                            conn = self.connections[alias]
                        except Exception as re_err:
                            logger.error(f"Переподключение не удалось: {re_err}")
                            raise DatabaseError(
                                f"Ошибка при выполнении запроса (переподключение не удалось): {e}",
                                original_error=e,
                            ) from e
                    else:
                        error_msg = f"Ошибка при выполнении запроса (после переподключения): {e}"
                        logger.error(error_msg, exc_info=True)
                        raise DatabaseError(error_msg, original_error=e) from e
                except psycopg2.Error as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    error_msg = f"Ошибка при выполнении запроса: {e}"
                    logger.error(error_msg, exc_info=True)
                    raise DatabaseError(error_msg, original_error=e) from e

    def fetch_one(self, query, params=None):
        """
        Выполняет SQL-запрос и возвращает одну строку результата из БД по умолчанию.
        """
        with self.lock:
            conn = self.connection
            max_retries = 1
            for attempt in range(max_retries + 1):
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(query, params)
                        result = cursor.fetchone()
                        conn.commit()
                        return result[0] if result else None
                except (psycopg2.InterfaceError, psycopg2.OperationalError) as e:
                    if attempt < max_retries:
                        logger.warning(f"fetch_one: соединение потеряно, переподключение: {e}")
                        try:
                            self._reconnect(self.default_alias)
                            conn = self.connections[self.default_alias]
                            self.connection = conn
                        except Exception:
                            raise DatabaseError(
                                f"Ошибка fetch_one (переподключение не удалось): {e}",
                                original_error=e,
                            ) from e
                    else:
                        raise DatabaseError(f"Ошибка fetch_one: {e}", original_error=e) from e
                except psycopg2.Error as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    error_msg = f"Ошибка при выполнении запроса: {e}"
                    logger.error(error_msg, exc_info=True)
                    raise DatabaseError(error_msg, original_error=e) from e
    
    @contextmanager
    def get_cursor(self, alias: Optional[str] = None):
        """
        Контекстный менеджер для получения курсора.
        Автоматически коммитит изменения или откатывает при ошибке.
        При потере соединения — переподключается.
        
        :yields: Курсор базы данных
        """
        use_alias = alias or self.default_alias
        with self.lock:
            conn = self.connections.get(use_alias)
            if conn is None:
                raise DatabaseError(f"Неизвестный алиас базы данных: {use_alias}")
            
            # Проверяем, что соединение живо; если нет — переподключаемся
            try:
                if conn.closed:
                    logger.warning(f"get_cursor: соединение {use_alias} закрыто, переподключение...")
                    self._reconnect(use_alias)
                    conn = self.connections[use_alias]
            except Exception as e:
                logger.error(f"get_cursor: переподключение не удалось: {e}")
                raise DatabaseError(f"Не удалось переподключиться ({use_alias})", original_error=e)
            
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except (psycopg2.InterfaceError, psycopg2.OperationalError) as e:
                logger.warning(f"get_cursor: соединение потеряно mid-query ({use_alias}): {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                cursor.close()

    def close(self):
        """
        Закрывает все соединения с базой данных.

        :return: None
        """
        try:
            # No need to close cursors as we don't store them anymore
            pass
            for alias, conn in list(self.connections.items()):
                try:
                    if conn:
                        conn.close()
                except Exception as e:
                    logger.error(f"Ошибка при закрытии соединения {alias}: {e}", exc_info=True)
        finally:
            self.connections.clear()
