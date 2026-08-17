from database_work.database_connection import DatabaseManager

from utils.logger_config import get_logger
from utils.cache import get_cache

# Получаем logger (только ошибки в файл)
logger = get_logger()

# Получаем кэш для часто используемых запросов
cache = get_cache()

class DatabaseIDFetcher:
    """
    Класс для извлечения id записей из различных таблиц базы данных по заданным значениям.
    Атрибуты:
        db_manager (DatabaseManager): Объект для работы с подключением к базе данных.
        cursor (cursor): Общий курсор для выполнения запросов.
    """

    def __init__(self):
        """
        Инициализация объекта DatabaseIDFetcher.

        Создает экземпляр DatabaseManager для выполнения запросов к базе данных.
        """

        self.db_manager = DatabaseManager()
        self.cursor = None  # Инициализируем курсор как None
    
    def __del__(self):
        """Деструктор для закрытия соединения при удалении объекта."""
        if hasattr(self, 'cursor') and self.cursor:
            try:
                self.cursor.close()
            except:
                pass
        if hasattr(self, 'db_manager') and self.db_manager:
            try:
                self.db_manager.close()
            except:
                pass

    def get_cursor(self):
        """
        Метод для получения или создания курсора.
        Если курсор уже существует, возвращает его.
        Если курсор не существует, создаёт новый.
        """
        if self.cursor is None:
            self.cursor = self.db_manager.connection.cursor()
        return self.cursor

    def fetch_id(self, table_name, column_name, value):
        """
        Универсальный метод для получения id записи по заданному значению в указанной таблице.
        Использует кэширование для часто используемых запросов.
        
        Возвращает:
        - int: id записи, если найдена
        - None: если запись не найдена (нормальная ситуация)
        - Выбрасывает исключение: если ошибка доступа к БД (критическая ситуация)
        """
        # Создаем ключ для кэша
        cache_key = f"{table_name}:{column_name}:{value}"
        
        # Пытаемся получить из кэша
        if cache.has(cache_key):
            cached_value = cache.get(cache_key)
            return cached_value
        
        query = f"SELECT id FROM {table_name} WHERE {column_name} = %s"
        params = (value,)

        # Получаем курсор и выполняем запрос
        try:
            cursor = self.get_cursor()  # Получаем курсор (создаём, если не существует)
            cursor.execute(query, params)
            result = cursor.fetchone()
            if result:
                result_id = result[0]  # Возвращаем id
                # Сохраняем в кэш
                cache.set(cache_key, result_id)
                return result_id
            else:
                # Сохраняем None в кэш (будет сохранен как NOT_FOUND маркер)
                cache.set(cache_key, None)
                return None
        except Exception as e:
            # При ошибке БД пробрасываем исключение дальше - это критическая ошибка
            error_msg = f"КРИТИЧЕСКАЯ ОШИБКА БД при получении id из {table_name} (колонка {column_name}, значение {value}): {e}"
            logger.error(error_msg, exc_info=True)
            raise  # Пробрасываем исключение, чтобы вызывающий код знал об ошибке

    def get_collection_codes_okpd_id(self, code):
        """
        Получает id записи из таблицы collection_codes_okpd по коду.
        :param code: Код для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("collection_codes_okpd", "code", code)

    def get_customer_id(self, inn):
        """
        Получает id записи из таблицы customer по имени (ИНН).
        :param inn: ИНН для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("customer", "customer_inn", inn)

    def get_contractor_id(self, inn):
        """
        Получает id записи из таблицы contractor по имени (ИНН).

        :param inn: ИНН для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("contractor", "inn", inn)

    def get_dates_id(self, date_value):
        """
        Получает id записи из таблицы dates по значению даты.

        :param date_value: Дата для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("dates", "date", date_value)

    def get_file_names_xml_id(self, file_name):
        """
        Получает id записи из таблицы file_names_xml по имени файла.

        :param file_name: Имя файла для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("file_names_xml", "file_name", file_name)

    def get_key_words_names_id(self, keyword):
        """
        Получает id записи из таблицы key_words_names по ключевому слову.

        :param keyword: Ключевое слово для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("key_words_names", "keyword", keyword)

    def get_key_words_names_documentations_id(self, keyword):
        """
        Получает id записи из таблицы key_words_names_documentations по ключевому слову.

        :param keyword: Ключевое слово для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("key_words_names_documentations", "keyword", keyword)

    def get_links_documentation_223_fz_id(self, link):
        """
        Получает id записи из таблицы links_documentation_223_fz по ссылке.

        :param link: Ссылка для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("links_documentation_223_fz", "link", link)

    def get_links_documentation_44_fz_id(self, link):
        """
        Получает id записи из таблицы links_documentation_44_fz по ссылке.

        :param link: Ссылка для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("links_documentation_44_fz", "link", link)

    def get_okpd_from_users_id(self, code):
        """
        Получает id записи из таблицы okpd_from_users по коду.

        :param code: Код для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("okpd_from_users", "code", code)

    def get_reestr_contract_223_fz_id(self, contract_number):
        """
        Получает id записи из таблицы reestr_contract_223_fz по номеру контракта.

        :param contract_number: Номер контракта для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("reestr_contract_223_fz", "contract_number", contract_number)

    def get_reestr_contract_44_fz_id(self, contract_number):
        """
        Получает id записи из таблицы reestr_contract_44_fz по номеру контракта.

        :param contract_number: Номер контракта для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("reestr_contract_44_fz", "contract_number", contract_number)

    def get_reestr_contract_44_fz_commission_work_id(self, contract_number):
        return self.fetch_id("reestr_contract_44_fz_commission_work", "contract_number", contract_number)

    def get_reestr_contract_223_fz_commission_work_id(self, contract_number):
        return self.fetch_id("reestr_contract_223_fz_commission_work", "contract_number", contract_number)

    def check_contract_in_any_table(self, contract_number, end_date=None, fz_type=None):
        """
        Проверяет наличие контракта в реестре.

        end_date >= сегодня → только main + commission (быстрый путь для PRIZ).
        Иначе → полный обход (RGK, старые закупки).
        """
        from database_work.contract_registry_locator import ContractRegistryLocator

        location = ContractRegistryLocator().find_by_number(
            contract_number,
            end_date=end_date,
            fz_type=fz_type,
        )
        if location is None:
            return (None, None)
        return (location.table_name, location.record_id)

    def get_contract_id_from_table(self, table_name, contract_number):
            """Ищет контракт в конкретной таблице по номеру. Возвращает id или None."""
            return self.fetch_id(table_name, "contract_number", contract_number)

    def get_region_id(self, region_code):
        """
        Получает id записи из таблицы region по коду региона.

        :param region_code: Код региона для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("region", "code", region_code)

    def get_stop_words_names_id(self, word):
        """
        Получает id записи из таблицы stop_words_names по слову.

        :param word: Слово для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("stop_words_names", "word", word)

    def get_trading_platform_id(self, name):
        """
        Получает id записи из таблицы trading_platform по имени.

        :param name: Имя торговой платформы для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("trading_platform", "trading_platform_name", name)

    def get_users_id(self, username):
        """
        Получает id записи из таблицы users по имени пользователя.

        :param username: Имя пользователя для поиска.
        :return: id записи или None, если не найдено.
        """
        return self.fetch_id("users", "username", username)

    def get_okpd_id(self, okpd_code):
        """
                Получает id записи из таблицы users по имени пользователя.

                :param username: Имя пользователя для поиска.
                :return: id записи или None, если не найдено.
                """
        return self.fetch_id("collection_codes_okpd", "sub_code", okpd_code)

    def contract_number_44_fz_id(self, contract_number_44_fz):
        """
                Получает id записи из таблицы users по имени пользователя.

                :param username: Имя пользователя для поиска.
                :return: id записи или None, если не найдено.
                """

        return self.fetch_id("reestr_contract_44_fz", "contract_number", contract_number_44_fz)

    def contract_number_223_fz_id(self, contract_number_223_fz):
        """
                Получает id записи из таблицы users по имени пользователя.

                :param username: Имя пользователя для поиска.
                :return: id записи или None, если не найдено.
                """
        return self.fetch_id("reestr_contract_223_fz", "contract_number", contract_number_223_fz)


    def close(self):
        """
        Закрывает соединение с базой данных.
        """
        self.db_manager.close()
