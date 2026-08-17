from database_work.database_connection import DatabaseManager
from psycopg2 import IntegrityError
from secondary_functions import load_config

from utils.logger_config import get_logger
from utils import stats as stats_collector

# Получаем logger (только ошибки в файл)
logger = get_logger()


class DatabaseOperations:
    def __init__(self, config_path="config.ini"):

        self.db_manager = DatabaseManager()

        self.config = load_config(config_path)
        if not self.config:
            raise ValueError("Ошибка загрузки конфигурации!")

        self.tags_paths = self.config['tags']

    def _prepare_contact(self, customer_data, tags_file):
        """Подготовка поля contact (ФИО) для записи."""
        if tags_file == self.tags_paths['get_tags_44_new']:
            contact_parts = [
                (customer_data.get("contact_last_name") or "").strip(),
                (customer_data.get("contact_first_name") or "").strip(),
                (customer_data.get("contact_middle_name") or "").strip()
            ]
        elif tags_file == self.tags_paths['get_tags_223_new']:
            contact_parts = [
                customer_data.get("contact_last_name") or None,
                customer_data.get("contact_first_name") or None,
                customer_data.get("contact_middle_name") or None
            ]
        else:
            contact_parts = []

        # Убираем пустые строки, заменяем на None
        contact = " ".join([part for part in contact_parts if part]).strip() or None
        return contact

    def _update_field(self, existing_value, new_value):
        """Если новое значение отличается от существующего, добавляем его через ;"""
        if not new_value:  # Если новое значение пустое или None, оставляем старое
            return existing_value
        if existing_value and existing_value != new_value:
            return f"{existing_value}; {new_value}"
        return new_value

    def _is_contact_exists(self, contact, cursor):
        """Проверяем, существует ли уже контакт в базе данных."""
        if contact is None:
            return False  # Если контакт равен None, значит, его не существует в базе
        try:
            cursor.execute("""SELECT COUNT(1) FROM customer WHERE contact = %s""", (contact,))
            count = cursor.fetchone()[0]
            return count > 0
        except Exception as e:
            logger.error(f"Ошибка при проверке контакта: {e}")
            return False

    def _insert_data(self, table_name, data, cursor=None):
        """Универсальная функция для вставки данных в любую таблицу."""
        try:
            use_local_cursor = False
            if cursor is None:
                cursor = self.db_manager.connection.cursor()
                use_local_cursor = True  # Если курсор не передан, значит, коммитить должны сами

            # Проверяем и заменяем пустые значения
            for column, value in data.items():
                if value is None or value == '':
                    data[column] = None  # Заменяем пустую строку на None

            # Проверка на уникальность контакта
            contact = data.get('contact')
            if contact and self._is_contact_exists(contact, cursor):
                # Считаем пропуск из-за существующего контакта
                try:
                    stats_collector.increment(f"{table_name}_skipped_contact", 1)
                except Exception:
                    pass
                return None

            columns = ', '.join(data.keys())
            values = tuple(data.values())
            placeholders = ', '.join(['%s'] * len(data))

            insert_query = f"""
                INSERT INTO {table_name} ({columns})
                VALUES ({placeholders}) RETURNING id
            """
            cursor.execute(insert_query, values)
            inserted_id = cursor.fetchone()[0]

            # Если курсор локальный, коммитим
            if use_local_cursor:
                self.db_manager.connection.commit()

            # Инкрементируем статистику успешных вставок по имени таблицы
            try:
                stats_collector.increment(table_name, 1)
            except Exception:
                # Никогда не падаем из-за подсчёта статистики
                pass

            return inserted_id

        except IntegrityError as e:
            # Это нормально для дублирующихся записей - считаем пропуск
            # Но нужно откатить транзакцию, чтобы она не осталась в состоянии ошибки
            try:
                self.db_manager.connection.rollback()
            except Exception:
                pass
            try:
                stats_collector.increment(f"{table_name}_skipped_duplicate", 1)
            except Exception:
                pass
            # Логируем детали для подрядчиков и заказчиков, чтобы понять причину
            if table_name in ['contractor', 'customer']:
                logger.error(f"IntegrityError при вставке {table_name}: {e} | Данные: {data}")
            return None
        except Exception as e:
            # Детальное логирование для подрядчиков и заказчиков
            if table_name in ['contractor', 'customer']:
                entity_name = "подрядчика" if table_name == 'contractor' else "заказчика"
                inn_field = 'inn' if table_name == 'contractor' else 'customer_inn'
                inn = data.get(inn_field, 'неизвестен')
                logger.error(f"Ошибка при вставке {entity_name} в БД (ИНН {inn}): {e}", exc_info=True)
                logger.error(f"Данные {entity_name}: {data}")
                # Проверяем длину полей
                for key, value in data.items():
                    if value and isinstance(value, str) and len(value) > 500:
                        logger.error(f"Поле {key} слишком длинное ({len(value)} символов): {value[:100]}...")
            else:
                logger.error(f"Ошибка при вставке данных в {table_name}: {e}", exc_info=True)
            try:
                self.db_manager.connection.rollback()
            except Exception:
                pass
            return None
        finally:
            if use_local_cursor:
                cursor.close()

    def insert_customer(self, customer_data, tags_file):
        """Вставка нового заказчика в таблицу с валидацией."""
        try:
            # Проверяем наличие обязательного поля ИНН
            inn = customer_data.get('customer_inn')
            if not inn or (isinstance(inn, str) and not inn.strip()):
                logger.error(f"Попытка вставить заказчика без ИНН. Данные: {customer_data}")
                return None
            
            contact = self._prepare_contact(customer_data, tags_file)
            customer_data['contact'] = contact

            # Удаляем ненужные ключи, которых нет в БД
            customer_data.pop("contact_last_name", None)
            customer_data.pop("contact_first_name", None)
            customer_data.pop("contact_middle_name", None)

            result = self._insert_data('customer', customer_data)
            
            if not result:
                # Детальное логирование при неудачной вставке
                logger.error(f"Не удалось добавить заказчика с ИНН {inn}. Данные: {customer_data}")
            
            return result

        except Exception as e:
            logger.error(f"Ошибка при вставке заказчика с ИНН {customer_data.get('customer_inn', 'неизвестен')}: {e}", exc_info=True)
            logger.error(f"Данные заказчика: {customer_data}")
            return None

    def update_customer(self, customer_data, customer_id, tags_file):
        """Обновление данных заказчика."""
        try:
            with self.db_manager.connection.cursor() as cursor:
                contact = self._prepare_contact(customer_data, tags_file)
                legal_address = customer_data.get("customer_legal_address")
                actual_address = customer_data.get("customer_actual_address")
                phone = customer_data.get("contact_phone")
                email = customer_data.get("contact_email")

                cursor.execute(""" 
                    SELECT contact, contact_phone, contact_email, customer_legal_address, customer_actual_address
                    FROM customer WHERE id = %s
                """, (customer_id,))
                existing_customer = cursor.fetchone()

                if existing_customer:
                    existing_contact, existing_phone, existing_email, existing_legal_address, existing_actual_address = existing_customer

                    update_fields = []
                    update_values = []

                    if legal_address and legal_address != existing_legal_address:
                        update_fields.append("customer_legal_address = %s")
                        update_values.append(legal_address)

                    if actual_address and actual_address != existing_actual_address:
                        update_fields.append("customer_actual_address = %s")
                        update_values.append(actual_address)

                    new_contact = self._update_field(existing_contact, contact)
                    if new_contact != existing_contact:
                        update_fields.append("contact = %s")
                        update_values.append(new_contact)

                    new_phone = self._update_field(existing_phone, phone)
                    if new_phone != existing_phone:
                        update_fields.append("contact_phone = %s")
                        update_values.append(new_phone)

                    new_email = self._update_field(existing_email, email)
                    if new_email != existing_email:
                        update_fields.append("contact_email = %s")
                        update_values.append(new_email)

                    if update_fields:
                        update_query = f"""
                            UPDATE customer
                            SET {', '.join(update_fields)}
                            WHERE id = %s
                        """
                        update_values.append(customer_id)
                        cursor.execute(update_query, tuple(update_values))
                        self.db_manager.connection.commit()  # <-- ДОБАВИЛ КОМИТ
                else:
                    logger.error(f"Запись с id {customer_id} не найдена для обновления в таблице customer")
                    return None

                return customer_id

        except Exception as e:
            logger.error(f"Ошибка при обновлении данных в customer: {e}")
            self.db_manager.connection.rollback()
            return None

    def insert_file_name(self, file_name):
        """Вставляет имя обработанного XML-файла в таблицу file_names_xml."""
        try:
            with self.db_manager.connection.cursor() as cursor:  # Используем контекстный менеджер
                insert_query = """
                    INSERT INTO file_names_xml (file_name)
                    VALUES (%s) RETURNING id;
                """
                cursor.execute(insert_query, (file_name,))
                inserted_id = cursor.fetchone()[0]
                self.db_manager.connection.commit()

                # Успешно добавили имя файла — фиксируем статистику
                try:
                    stats_collector.increment('file_names_xml', 1)
                except Exception:
                    pass

                return inserted_id

        except IntegrityError as e:
            # Это нормально, если файл уже существует
            return None
        except Exception as e:
            logger.error(f"Ошибка при вставке имени файла {file_name}: {e}")
            self.db_manager.connection.rollback()
            return None

    def _update_existing_contract(self, contract_id, contract_data):
        """Обновление данных существующего контракта."""
        try:
            # Проверяем состояние транзакции - если она в состоянии ошибки, делаем rollback
            if self.db_manager.connection.status == 1:  # 1 = STATUS_IN_ERROR
                try:
                    self.db_manager.connection.rollback()
                except Exception:
                    pass
            
            with self.db_manager.connection.cursor() as cursor:
                update_columns = []
                update_values = []

                for column, value in contract_data.items():
                    if value is not None:
                        update_columns.append(f"{column} = %s")
                        update_values.append(value)

                if update_columns:
                    update_columns.append("updated_at = NOW()")
                    update_query = f"""
                        UPDATE reestr_contract_44_fz
                        SET {', '.join(update_columns)}
                        WHERE id = %s
                    """
                    update_values.append(contract_id)
                    cursor.execute(update_query, tuple(update_values))
                    self.db_manager.connection.commit()

                    return contract_id
                else:
                    return contract_id
        except Exception as e:
            logger.error(f"Ошибка при обновлении контракта {contract_id}: {e}")
            try:
                self.db_manager.connection.rollback()
            except Exception:
                pass
            return None

    # Пример вставки в другие таблицы, аналогично insert_customer
    def insert_trading_platform(self, trading_platform_data, cursor=None):
        return self._insert_data('trading_platform', trading_platform_data, cursor)

    def insert_reestr_contract_44_fz(self, contract_data, cursor=None):
        return self._insert_data('reestr_contract_44_fz', contract_data, cursor)

    def insert_reestr_contract_615_pp(self, contract_data, cursor=None):
        return self._insert_data('reestr_contract_615_pp', contract_data, cursor)

    def insert_reestr_contract_615_pp_commission_work(self, contract_data, cursor=None):
        return self._insert_data('reestr_contract_615_pp_commission_work', contract_data, cursor)

    def insert_link_documentation_44_fz(self, links_44_fz_data, cursor=None):
        payload = dict(links_44_fz_data)
        payload.setdefault('contract_id', None)
        payload.setdefault('contract_number', None)
        # Не валидируем contract_id только против open-таблицы: контракт мог уже
        # переехать в awarded (тот же id). Храним как есть, ищем по обоим полям.
        return self._insert_data('links_documentation_44_fz', payload, cursor)

    def insert_reestr_contract_223_fz(self, contract_data, cursor=None):
        return self._insert_data('reestr_contract_223_fz', contract_data, cursor)

    def insert_link_documentation_223_fz(self, links_44_fz_data, cursor=None):
        payload = dict(links_44_fz_data)
        payload.setdefault('contract_id', None)
        payload.setdefault('contract_number', None)
        return self._insert_data('links_documentation_223_fz', payload, cursor)

    def insert_contractor(self, contractor_data, cursor=None):
        """
        Вставка подрядчика с валидацией и нормализацией данных.
        """
        # Проверяем наличие обязательного поля ИНН
        inn = contractor_data.get('inn')
        if not inn or (isinstance(inn, str) and not inn.strip()):
            logger.error(f"Попытка вставить подрядчика без ИНН. Данные: {contractor_data}")
            return None
        
        # Создаем копию данных для нормализации
        normalized_data = {}
        
        # Максимальные длины полей (примерные, нужно проверить схему БД)
        max_lengths = {
            'short_name': 500,
            'full_name': 1000,
            'inn': 20,
            'kpp': 20,
            'legal_address': 1000,
            'email': 255,
            'phone': 100,
        }
        
        for key, value in contractor_data.items():
            if value is None:
                normalized_data[key] = None
            elif isinstance(value, str):
                # Убираем лишние пробелы
                value = value.strip()
                # Если пустая строка после trim - делаем None (кроме ИНН)
                if not value:
                    if key == 'inn':
                        # ИНН обязателен, не может быть пустым
                        logger.error(f"ИНН подрядчика пустой после нормализации. Исходные данные: {contractor_data}")
                        return None
                    normalized_data[key] = None
                else:
                    # Обрезаем слишком длинные строки
                    max_len = max_lengths.get(key, 1000)
                    if len(value) > max_len:
                        logger.warning(f"Поле {key} обрезано с {len(value)} до {max_len} символов для подрядчика ИНН {inn}")
                        value = value[:max_len]
                    normalized_data[key] = value
            else:
                # Для не-строковых значений оставляем как есть
                normalized_data[key] = value
        
        # short_name NOT NULL: если пусто - берём full_name (оба поля NOT NULL в схеме)
        if not normalized_data.get('short_name') and normalized_data.get('full_name'):
            normalized_data['short_name'] = normalized_data['full_name'][:500]

        return self._insert_data('contractor', normalized_data, cursor)

    def update_commission_work_44_by_number(self, contract_number, delivery_start_date=None, delivery_end_date=None):
        try:
            with self.db_manager.connection.cursor() as cursor:
                fields = []
                values = []
                if delivery_start_date:
                    fields.append("delivery_start_date = %s")
                    values.append(delivery_start_date)
                if delivery_end_date:
                    fields.append("delivery_end_date = %s")
                    values.append(delivery_end_date)
                if fields:
                    query = f"""
                        UPDATE reestr_contract_44_fz_commission_work
                        SET {', '.join(fields)}
                        WHERE contract_number = %s
                    """
                    values.append(contract_number)
                    cursor.execute(query, tuple(values))
                    self.db_manager.connection.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка обновления commission_work 44 по номеру {contract_number}: {e}")
            try:
                self.db_manager.connection.rollback()
            except Exception:
                pass
            return False

    def update_commission_work_44_full(self, contract_data):
        """
        Полное обновление записи в reestr_contract_44_fz_commission_work.
        Обновляет все поля, включая подрядчика, стоимость и другие данные.
        """
        try:
            with self.db_manager.connection.cursor() as cursor:
                update_fields = []
                update_values = []
                
                # Список полей, которые могут обновляться
                possible_fields = [
                    'contract_number', 'contract_price', 'customer_name', 
                    'contractor_id', 'delivery_start_date', 'delivery_end_date',
                    'contract_subject', 'region_id', 'okpd2_code', 'okved2_code',
                    'customer_inn', 'contractor_inn', 'trading_platform_id'
                ]
                
                for field in possible_fields:
                    if field in contract_data and contract_data[field] is not None:
                        update_fields.append(f"{field} = %s")
                        update_values.append(contract_data[field])
                
                if update_fields:
                    update_query = f"""
                        UPDATE reestr_contract_44_fz_commission_work
                        SET {', '.join(update_fields)}
                        WHERE contract_number = %s
                    """
                    update_values.append(contract_data['contract_number'])
                    cursor.execute(update_query, tuple(update_values))
                    self.db_manager.connection.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка полного обновления commission_work 44 для контракта {contract_data.get('contract_number')}: {e}")
            try:
                self.db_manager.connection.rollback()
            except Exception:
                pass
            return False

    def update_commission_work_223_by_number(self, contract_number, delivery_start_date=None, delivery_end_date=None):
        try:
            with self.db_manager.connection.cursor() as cursor:
                fields = []
                values = []
                if delivery_start_date:
                    fields.append("delivery_start_date = %s")
                    values.append(delivery_start_date)
                if delivery_end_date:
                    fields.append("delivery_end_date = %s")
                    values.append(delivery_end_date)
                if fields:
                    query = f"""
                        UPDATE reestr_contract_223_fz_commission_work
                        SET {', '.join(fields)}
                        WHERE contract_number = %s
                    """
                    values.append(contract_number)
                    cursor.execute(query, tuple(values))
                    self.db_manager.connection.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка обновления commission_work 223 по номеру {contract_number}: {e}")
            try:
                self.db_manager.connection.rollback()
            except Exception:
                pass
            return False

    def update_commission_work_223_full(self, contract_data):
        try:
            with self.db_manager.connection.cursor() as cursor:
                update_fields = []
                update_values = []

                possible_fields = [
                    'contract_number', 'contract_price', 'customer_name',
                    'contractor_id', 'delivery_start_date', 'delivery_end_date',
                    'contract_subject', 'region_id', 'okpd2_code', 'okved2_code',
                    'customer_inn', 'contractor_inn', 'trading_platform_id'
                ]

                for field in possible_fields:
                    if field in contract_data and contract_data[field] is not None:
                        update_fields.append(f"{field} = %s")
                        update_values.append(contract_data[field])

                if update_fields:
                    update_query = f"""
                        UPDATE reestr_contract_223_fz_commission_work
                        SET {', '.join(update_fields)}
                        WHERE contract_number = %s
                    """
                    update_values.append(contract_data['contract_number'])
                    cursor.execute(update_query, tuple(update_values))
                    self.db_manager.connection.commit()
                    return True
                return False
        except Exception as e:
            logger.error(
                f"Ошибка полного обновления commission_work 223 для контракта {contract_data.get('contract_number')}: {e}"
            )
            try:
                self.db_manager.connection.rollback()
            except Exception:
                pass
            return False

    def _update_existing_contract_223(self, contract_id, contract_data):
        try:
            if self.db_manager.connection.status == 1:
                try:
                    self.db_manager.connection.rollback()
                except Exception:
                    pass

            with self.db_manager.connection.cursor() as cursor:
                update_columns = []
                update_values = []

                for column, value in contract_data.items():
                    if value is not None:
                        update_columns.append(f"{column} = %s")
                        update_values.append(value)

                if update_columns:
                    update_columns.append("updated_at = NOW()")
                    update_query = f"""
                        UPDATE reestr_contract_223_fz
                        SET {', '.join(update_columns)}
                        WHERE id = %s
                    """
                    update_values.append(contract_id)
                    cursor.execute(update_query, tuple(update_values))
                    self.db_manager.connection.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка при обновлении данных в reestr_contract_223_fz: {e}")
            try:
                self.db_manager.connection.rollback()
            except Exception:
                pass
            return False
