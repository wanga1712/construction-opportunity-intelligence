from file_delete.file_deleter import FileDeleter
from database_work.database_connection import DatabaseManager
from database_work.database_id_fetcher import DatabaseIDFetcher

from utils.logger_config import get_logger

# Получаем logger (только ошибки в файл)
logger = get_logger()


class DatabaseCheckManager:
    """
    Класс для управления проверкой и взаимодействием с базой данных.

    Этот класс включает методы для:
    - Проверки существования ОКПД в базе данных.
    - Проверки, записано ли имя файла в таблице `file_names_xml`..
    - Проверки ИНН заказчика и получения его ID из базы данных.
    """

    def __init__(self):
        """
        Инициализирует экземпляры классов для работы с базой данных.

        Использует `DatabaseManager` для взаимодействия с базой данных и
        `DatabaseIDFetcher` для получения ID заказчика.
        """

        self.db_manager = DatabaseManager()
        self.id_fetcher = DatabaseIDFetcher()

    def get_db_manager(self):
        """
        Возвращает экземпляр `DatabaseManager`.

        :return: Экземпляр класса `DatabaseManager`
        """
        return self.db_manager

    def close(self):
        """
        Закрывает соединение с базой данных.

        :return: None
        """
        self.db_manager.close()

    def check_contract_number_44_fz(self, contract_number_44_fz):
        """
        Проверяет, существует ли номер контракта 44-ФЗ в базе данных.

        :param contract_number_44_fz: Номер контракта 44-ФЗ для проверки.
        :return: True, если контракт найден, иначе False.
        """
        cursor = None
        try:
            query = """
            SELECT EXISTS(
                SELECT 1 
                FROM reestr_contract_44_fz 
                WHERE contract_number = %s
            );
            """
            cursor = self.db_manager.cursor  # Получаем курсор
            cursor.execute(query, (contract_number_44_fz,))
            result = cursor.fetchone()

            # Если результат возвращает False, значит контракт не найден
            return result[0] if result else False

        except Exception as e:
            logger.exception(f"Ошибка при проверке номера контракта 44-ФЗ: {e}")
            return False

        finally:
            # Не закрываем курсор и соединение здесь, так как они используются повторно
            # Управление ресурсами должно быть на более высоком уровне
            pass


    # Удалить за ненадобностью после проверки
    # def check_inn_and_get_id_customer(self, inn):
    #     """
    #     Проверяет, существует ли ИНН в таблице `customer` и возвращает ID.
    #
    #     :param inn: ИНН заказчика, который необходимо проверить.
    #     :return: ID заказчика, если ИНН найден в базе данных, иначе None.
    #     """
    #     customer_id = self.id_fetcher.get_customer_id(inn)
    #
    #     if customer_id:
    #         logger.info(f"ИНН {inn} найден в базе данных, id: {customer_id}")
    #         return customer_id  # Возвращаем ID заказчика, если он найден
    #
    #     logger.warning(f"ИНН {inn} не найден в базе данных.")
    #     return None  # Если ИНН не найден, просто возвращаем None, без попытки обновить базу