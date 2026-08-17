import json
import xml.etree.ElementTree as ET
import re
from datetime import datetime

from utils.logger_config import get_logger
from secondary_functions import load_config
from database_work.database_operations import DatabaseOperations
from database_work.database_id_fetcher import DatabaseIDFetcher
from file_delete.file_deleter import FileDeleter

# Получаем logger (только ошибки в файл)
logger = get_logger()

class XMLParser:
    """
    Класс для обработки XML-файлов в указанной директории.
    """

    def __init__(self, config_path="config.ini"):
        """
        Загружает конфигурацию и путь к XML-файлам из config.ini.
        """

        # Инициализируем методы для работы с базой данных внутри XMLParser
        self.database_operations = DatabaseOperations()
        self.db_id_fetcher = DatabaseIDFetcher()

        self.config = load_config(config_path)
        if not self.config:
            raise ValueError("Ошибка загрузки конфигурации!")

        # Пути к папкам с XML и теги для каждой папки из конфигурации
        self.xml_paths = self.config['path']
        self.tags_paths = self.config['tags']

    @staticmethod
    def remove_namespaces(xml_string):
        """
        Полностью удаляет все пространства имен из XML-строки.
        Убирает как префиксы, так и их определения.
        """
        # Удаление всех атрибутов xmlns:... и xmlns="..."
        no_namespaces = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', xml_string)

        # Удаление всех префиксов вида <ns3:tag> и </ns3:tag>
        no_namespaces = re.sub(r'<(/?)(\w+):', r'<\1', no_namespaces)

        # Также важно удалить префикс внутри атрибутов, если он есть (например, ns5:href)
        no_namespaces = re.sub(r'(\s)(\w+):', r'\1', no_namespaces)

        return no_namespaces

    def load_json_tags(self, tags_path):
        """
        Загружает теги из указанного JSON файла.
        """
        try:
            with open(tags_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка при загрузке JSON файла с тегами {tags_path}: {e}")
            return None

    def _extract_contract_number_for_links(self, root, contract_tags):
        """????????? ????? ????????? ??? ?????????? ???????? ??????."""
        xpath = (contract_tags or {}).get('contract_number')
        if not xpath:
            return None
        element = root.find(f".//{xpath}")
        if element is not None and element.text:
            value = element.text.strip()
            return value or None
        return None

    def parse_reestr_contract_44_fz(self, root, tags, region_code, okpd_code, customer_id, platform_id, tags_file,
                                    file_path, xml_folder_path):
        """
        Парсит данные для таблицы реестра контрактов 44-ФЗ и вставляет в БД.
        Если поле 'auction_name' пустое, прекращает обработку и удаляет файл через FileDeleter.
        """
        found_tags = self._parse_common_contract_data(root, tags, region_code, okpd_code, customer_id, platform_id,
                                                      tags_file)

        # Проверяем, что поле auction_name не пустое
        if not found_tags.get('auction_name'):
            # Удаляем файл через FileDeleter
            file_deleter = FileDeleter(xml_folder_path)
            file_deleter.delete_single_file(file_path)
            # Прекращаем дальнейшую обработку
            return None

        # Если значение поля 'auction_name' присутствует, проверяем существование контракта
        contract_number = found_tags.get('contract_number')
        if contract_number:
            # Проверяем, есть ли контракт в любой таблице
            table_name, record_id = self.db_id_fetcher.check_contract_in_any_table(
                contract_number,
                end_date=found_tags.get('end_date'),
                fz_type='44',
            )

            if table_name:
                # Контракт уже существует - обновляем соответствующую таблицу
                if table_name == 'reestr_contract_44_fz_commission_work':
                    self.database_operations.update_commission_work_44_full(found_tags)
                elif table_name == 'reestr_contract_44_fz':
                    self.database_operations._update_existing_contract(record_id, found_tags)
                # Для других таблиц можно добавить соответствующую логику обновления
                return record_id
            else:
                # Контракт не существует - вставляем новую запись
                contract_id = self.database_operations.insert_reestr_contract_44_fz(found_tags)
                return contract_id
        else:
            # Нет номера контракта - не обрабатываем
            return None

    def parse_reestr_contract_223_fz(self, root, tags, region_code, okpd_code, customer_id, platform_id, tags_file,
                                     file_path, xml_folder_path):
        """
        Парсит данные для таблицы реестра контрактов 223-ФЗ и вставляет в БД.
        """
        # Парсим общие данные контракта
        found_tags = self._parse_common_contract_data(root, tags, region_code, okpd_code, customer_id, platform_id,
                                                      tags_file)

        # Проверяем, если нет значения для contract_number, пропускаем обработку и удаляем файл
        if not found_tags.get('contract_number'):
            # Удаляем файл через FileDeleter
            file_deleter = FileDeleter(xml_folder_path)
            file_deleter.delete_single_file(file_path)
            # Прекращаем дальнейшую обработку
            return None

        contract_number = found_tags.get('contract_number')
        if not contract_number:
            return None

        table_name, record_id = self.db_id_fetcher.check_contract_in_any_table(
            contract_number,
            end_date=found_tags.get('end_date'),
            fz_type='223',
        )
        if table_name:
            if table_name == 'reestr_contract_223_fz_commission_work':
                self.database_operations.update_commission_work_223_full(found_tags)
            elif table_name == 'reestr_contract_223_fz':
                self.database_operations._update_existing_contract_223(record_id, found_tags)
            return record_id

        contract_id = self.database_operations.insert_reestr_contract_223_fz(found_tags)
        return contract_id

    def parse_reestr_contract_615_pp(self, root, tags, region_code, okpd_code, customer_id, platform_id, tags_file,
                                     file_path, xml_folder_path, work_kind_tags=None, contractor_tags=None):
        """
        Парсит данные для таблицы реестра контрактов 615-ПП и вставляет в БД.
        XML: pprf615types (без OKPD2; виды работ в purchaseSubjectInfo).
        """
        if self.config.has_section('eis_615'):
            allowed_regions = {
                str(r).strip()
                for r in self.config.get('eis_615', 'regions', fallback='77,50').split(',')
                if str(r).strip()
            }
            if allowed_regions and str(region_code) not in allowed_regions:
                FileDeleter(xml_folder_path).delete_single_file(file_path)
                return None

        found_tags = self._parse_common_contract_data(root, tags, region_code, okpd_code, customer_id, platform_id,
                                                      tags_file)

        # 615-ПП не использует ОКПД
        found_tags['okpd_id'] = None

        # Виды работ (вместо ОКПД)
        work_kind_tags = work_kind_tags or {}
        work_kind_code = self._first_text(root, work_kind_tags.get('work_kind_code', 'purchaseSubjectInfo/code'))
        work_kind_name = self._first_text(root, work_kind_tags.get('work_kind_name', 'purchaseSubjectInfo/name'))
        if work_kind_code:
            found_tags['work_kind_code'] = work_kind_code
        if work_kind_name:
            found_tags['work_kind_name'] = work_kind_name
            found_tags['auction_name'] = work_kind_name
        elif work_kind_code and not found_tags.get('auction_name'):
            found_tags['auction_name'] = f"Вид работ 615-ПП код {work_kind_code}"

        matched_kw = self._detect_waterproofing(root)
        found_tags['is_waterproofing'] = bool(matched_kw)
        found_tags['matched_keywords'] = ", ".join(matched_kw) if matched_kw else None
        strict = False
        if self.config.has_section('eis_615'):
            strict = self.config.getboolean('eis_615', 'hydro_filter_strict', fallback=False)
        if strict and not matched_kw:
            logger.info(f"615-ПП: пропуск без гидроизоляции {found_tags.get('contract_number')}")
            FileDeleter(xml_folder_path).delete_single_file(file_path)
            return None

        for date_key in ('start_date', 'end_date', 'delivery_start_date', 'delivery_end_date'):
            found_tags[date_key] = self._normalize_date(found_tags.get(date_key))

        contractor_id = None
        contractor_tags = contractor_tags or {}
        if contractor_tags:
            contractor_data = {}
            for field, xpath in contractor_tags.items():
                contractor_data[field] = self._first_text(root, xpath)
            if contractor_data.get('inn'):
                if not contractor_data.get('short_name'):
                    contractor_data['short_name'] = contractor_data.get('full_name')
                existing = None
                if hasattr(self.db_id_fetcher, 'get_contractor_id'):
                    existing = self.db_id_fetcher.get_contractor_id(contractor_data['inn'])
                if existing:
                    contractor_id = existing
                else:
                    contractor_id = self.database_operations.insert_contractor(contractor_data)
        found_tags['contractor_id'] = contractor_id

        if not found_tags.get('contract_number'):
            FileDeleter(xml_folder_path).delete_single_file(file_path)
            return None

        if not found_tags.get('auction_name'):
            logger.error(f"615-ПП: пустой auction_name/вид работ для {found_tags.get('contract_number')}")
            FileDeleter(xml_folder_path).delete_single_file(file_path)
            return None

        if found_tags.get('initial_price') is None:
            found_tags['initial_price'] = 0
        if not found_tags.get('tender_link'):
            found_tags['tender_link'] = (
                "https://zakupki.gov.ru/epz/capitalrepairs/card/general-info.html"
                f"?reestr-number={found_tags['contract_number']}"
            )

        contract_number = found_tags.get('contract_number')
        existing_id = self.db_id_fetcher.get_contract_id_from_table('reestr_contract_615_pp', contract_number)
        if existing_id:
            return existing_id

        allowed = {
            'contract_number', 'tender_link', 'start_date', 'end_date',
            'delivery_start_date', 'delivery_end_date', 'auction_name',
            'initial_price', 'final_price', 'guarantee_amount', 'customer_id',
            'contractor_id', 'trading_platform_id', 'okpd_id', 'customer',
            'warranty_size', 'delivery_region', 'delivery_address', 'region_id',
            'status_id', 'work_kind_code', 'work_kind_name',
            'is_waterproofing', 'matched_keywords',
        }
        insert_data = {k: v for k, v in found_tags.items() if k in allowed}
        try:
            return self.database_operations.insert_reestr_contract_615_pp(insert_data)
        except Exception as e:
            msg = str(e)
            if 'work_kind_' in msg or 'is_waterproofing' in msg or 'matched_keywords' in msg:
                insert_data.pop('work_kind_code', None)
                insert_data.pop('work_kind_name', None)
                insert_data.pop('is_waterproofing', None)
                insert_data.pop('matched_keywords', None)
                try:
                    self.database_operations.db_manager.connection.rollback()
                except Exception:
                    pass
                return self.database_operations.insert_reestr_contract_615_pp(insert_data)
            raise

    def _detect_waterproofing(self, root):
        """Ищет признаки гидроизоляции во всём тексте XML договора 615."""
        keywords_raw = "гидроизол,гидроизоляция,гидроизоляц,мембран,оклеечн,обмазочн,инъекцион,праймер битум"
        if self.config.has_section('eis_615'):
            keywords_raw = self.config.get('eis_615', 'hydro_keywords', fallback=keywords_raw)
        keywords = [k.strip().lower() for k in keywords_raw.split(',') if k.strip()]
        matched = []
        for el in root.iter():
            text_val = " ".join((el.text or "").split())
            if not text_val:
                continue
            low = text_val.lower()
            for kw in keywords:
                if kw in low and kw not in matched:
                    matched.append(kw)
        return matched

    def _parse_common_contract_data(self, root, tags, region_code, okpd_code, customer_id, platform_id, tags_file):
        """
        Общая логика парсинга данных для контрактов, используемая для 44-ФЗ и 223-ФЗ.
        """
        found_tags = {}

        # Парсинг общих данных
        for tag, xpath in tags.items():
            tag_without_namespace = xpath.split(":")[-1]
            elements = root.findall(f".//{tag_without_namespace}")

            if elements:
                values = [elem.text.strip() for elem in elements if elem.text and elem.text.strip()]
                found_tags[tag] = values[0] if values else None
            else:
                found_tags[tag] = None

            # Обрабатываем start_date, end_date и initial_price
            if tag == "start_date" and not found_tags[tag]:
                found_tags[tag] = datetime.now().strftime('%Y-%m-%d')

            if tag == "end_date" and not found_tags[tag]:
                found_tags[tag] = datetime.now().strftime('%Y-%m-%d')

            if tag == "initial_price" and not found_tags[tag]:
                found_tags[tag] = 0

        # Добавляем дополнительные параметры
        found_tags['region_id'] = self.db_id_fetcher.get_region_id(region_code)
        found_tags['okpd_id'] = self.db_id_fetcher.get_okpd_id(okpd_code) if okpd_code else None
        found_tags['customer_id'] = customer_id
        found_tags['trading_platform_id'] = platform_id

        return found_tags

    @staticmethod
    def _first_text(root, xpath: str):
        element = root.find(f".//{xpath}")
        if element is not None and element.text and element.text.strip():
            return element.text.strip()
        return None

    @staticmethod
    def _normalize_date(value):
        if not value:
            return None
        text = str(value).strip()
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            day = text[:10]
            if day.startswith("0001"):
                return None
            return day
        return text

    def parse_trading_platform(self, root, tags):
        """
        Парсит данные для таблицы trading_platform, проверяя наличие записи.
        Если запись уже есть, просто возвращает ее ID, иначе создает новую запись.
        """
        found_tags = {}

        # Парсим данные из XML
        for tag, xpath in tags.items():
            element = root.find(f".//{xpath}")  # Добавляем ".//" для поиска на любом уровне
            found_tags[tag] = element.text.strip() if element is not None and element.text else None

        # Получаем имя торговой площадки
        trading_platform_name = found_tags.get('trading_platform_name')

        # Если имя торговой площадки не найдено, ставим дефолтное значение
        if not trading_platform_name:
            trading_platform_name = "Торговая площадка не найдена"  # Присваиваем дефолтное значение

        # Проверяем, есть ли в базе запись с этим именем
        platform_id = self.db_id_fetcher.get_trading_platform_id(trading_platform_name)

        # Если площадка уже существует, возвращаем её ID
        if platform_id:
            return platform_id

        # Если площадки нет в БД, создаем новую запись
        found_tags['trading_platform_name'] = trading_platform_name

        # Проверяем наличие URL, если его нет, ставим дефолтный
        if not found_tags.get('trading_platform_url'):
            found_tags['trading_platform_url'] = "https://нет.ссылки"  # Устанавливаем дефолтный URL

        # Вставляем данные в таблицу
        platform_id = self.database_operations.insert_trading_platform(found_tags)

        if not platform_id:
            logger.error(f"Не удалось добавить торговую площадку '{trading_platform_name}' в БД")

        return platform_id  # Возвращаем ID, который был найден или создан

    def parse_links_documentation(self, root, links_documentation_tags, contract_id, tags_file, table_override=None, contract_number=None):
        """
        Парсит данные для таблицы links_documentation_44_fz (или 223_fz)
        и вызывает парсинг для таблицы printFormInfo.
        """
        found_tags = []

        for tag_name, tag_data in links_documentation_tags.items():
            xpath = tag_data.get("xpath")
            if not xpath:
                logger.error(f"Отсутствует xpath в секции {tag_name} для файла {tags_file}")
                continue

            # Ищем элементы по заданному XPath
            for elem in root.findall(xpath):
                # Если нет file_name, используем default_file_name, если он есть, или пропускаем
                file_name_tag = tag_data.get("file_name")
                if not file_name_tag:
                    # Если file_name отсутствует, используем default_file_name, если он есть
                    file_name_tag = tag_data.get("default_file_name", tag_name)

                file_name_elem = elem.find(file_name_tag)
                url_elem = elem.find(tag_data.get("document_links"))

                file_name = file_name_elem.text.strip() if file_name_elem is not None and file_name_elem.text else file_name_tag
                url = url_elem.text.strip() if url_elem is not None and url_elem.text else None

                # Если URL найден, добавляем информацию в список
                if url:
                    found_tags.append({
                        "file_name": file_name,
                        "document_links": url,
                        "contract_id": contract_id,
                        "contract_number": contract_number,
                    })

        # Вставляем все собранные данные для соответствующей таблицы в базу
        for entry in found_tags:
            if entry:
                if table_override == 'links_documentation_615_pp':
                    self.database_operations._insert_data('links_documentation_615_pp', entry)
                elif tags_file == self.tags_paths['get_tags_44_new']:
                    inserted_id = self.database_operations.insert_link_documentation_44_fz(entry)
                elif tags_file == self.tags_paths['get_tags_223_new']:
                    inserted_id = self.database_operations.insert_link_documentation_223_fz(entry)
                else:
                    logger.error(f"Неизвестный файл тегов: {tags_file}")
                    continue

        # Возвращаем все найденные данные
        return found_tags

    def parse_customer(self, root, tags, tags_file):
        """
        Парсит данные для таблицы customer, проверяя наличие ИНН в базе данных.
        Если ИНН существует, обновляет данные, если нет — добавляет нового заказчика.
        """
        found_tags = {}

        for tag, xpath in tags.items():
            element = root.find(f".//{xpath}")

            if element is None or element.text is None:
                found_tags[tag] = None
                continue

            try:
                if tags_file == self.tags_paths['get_tags_44_new']:
                    found_tags[tag] = element.text.strip() if element.text else None
                elif tags_file == self.tags_paths.get('get_tags_615_new'):
                    found_tags[tag] = element.text.strip() if element.text else None
                elif tags_file == self.tags_paths['get_tags_223_new']:
                    found_tags[tag] = element.text
                else:
                    logger.error(f"Неизвестный файл тегов: {tags_file}")
                    return None

            except AttributeError:
                logger.error(f"Ошибка при обработке тега '{tag}' в файле {tags_file}: element.text = {element.text}")
                found_tags[tag] = None

        # Проверяем наличие ИНН
        inn = found_tags.get('customer_inn')
        if inn:
            customer_id = self.db_id_fetcher.get_customer_id(inn)

            if customer_id:
                pass
            else:
                customer_data = found_tags
                customer_id = self.database_operations.insert_customer(customer_data, tags_file)
                if not customer_id:
                    logger.error(f"Не удалось добавить нового заказчика с ИНН {inn}")
        else:
            logger.error("ИНН не найден в данных заказчика")
            customer_id = None

        return customer_id

    def parse_xml_tags(self, file_path, region_code, okpd_code, xml_folder_path):
        """
        Функция для извлечения тегов для одной записи XML.
        :param file_path: Путь к конкретному XML файлу для обработки
        :param region_code: Код региона
        :param okpd_code: Код ОКПД для обработки
        """

        # Определяем, какой JSON файл использовать в зависимости от папки
        if xml_folder_path == self.xml_paths['reest_new_contract_archive_44_fz_xml']:
            tags_file = self.tags_paths['get_tags_44_new']
        elif xml_folder_path == self.xml_paths['reest_new_contract_archive_223_fz_xml']:
            tags_file = self.tags_paths['get_tags_223_new']
        elif self.config.has_section('eis_615') and xml_folder_path == self.config.get('eis_615', 'archive_xml', fallback=''):
            tags_file = self.tags_paths.get('get_tags_615_new') or self.tags_paths['get_tags_44_new']
        else:
            logger.error(f"Неизвестная папка: {xml_folder_path}")
            return None

        # Загружаем теги из соответствующего JSON файла
        tags = self.load_json_tags(tags_file)  # Определение файла тегов по пути

        if not tags_file:
            logger.error(f"Не удалось найти файл тегов для файла {file_path}")
            return None

        tags = self.load_json_tags(tags_file)
        if not tags:
            logger.error("Не удалось загрузить теги из JSON.")
            return None

        # Загружаем и парсим XML
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                xml_content = f.read()

            # Удаляем пространства имен перед парсингом
            cleaned_xml_content = self.remove_namespaces(xml_content)

            tree = ET.ElementTree(ET.fromstring(cleaned_xml_content))
            root = tree.getroot()

        except ET.ParseError as e:
            logger.error(f"Ошибка при парсинге XML-файла {file_path}: {e}")
            return

        # Получаем данные о заказчике
        customer_id = self.parse_customer(
            root,
            tags.get('customer', {}),
            tags_file  # Передаем сюда tags_file
        )

        # Получаем данные о торговой площадке
        platform_id = self.parse_trading_platform(root, tags.get('trading_platform', {}))

        # Выбираем правильную функцию для контракта
        is_615 = (self.config.has_section('eis_615') and
                  xml_folder_path == self.config.get('eis_615', 'archive_xml', fallback=''))

        if is_615:
            contract_id = self.parse_reestr_contract_615_pp(
                root, tags.get('reestr_contract', {}), region_code, okpd_code,
                customer_id, platform_id, tags_file, file_path, xml_folder_path,
                work_kind_tags=tags.get('work_kind', {}),
                contractor_tags=tags.get('contractor', {}),
            )
        elif tags_file == self.tags_paths['get_tags_44_new']:
            contract_id = self.parse_reestr_contract_44_fz(
                root,
                tags.get('reestr_contract', {}),
                region_code,
                okpd_code,
                customer_id,  # Передаем customer_id
                platform_id,
                tags_file,
                file_path,
                xml_folder_path
            )
        elif tags_file == self.tags_paths['get_tags_223_new']:
            contract_id = self.parse_reestr_contract_223_fz(
                root,
                tags.get('reestr_contract', {}),
                region_code,
                okpd_code,
                customer_id,  # Передаем customer_id
                platform_id,
                tags_file,
                file_path,
                xml_folder_path
            )

        if not contract_id:
            return

        # Парсим ссылки и документацию
        # contract_number извлекается из XML чтобы хранить ссылки по номеру контракта,
        # а не только по id — это позволяет найти ссылки после миграции в awarded таблицу.
        _cn_tags = tags.get('reestr_contract', {})
        contract_number_for_links = self._extract_contract_number_for_links(root, _cn_tags)
        links_documentation = self.parse_links_documentation(
            root,
            tags.get('links_documentation', {}),
            contract_id,
            tags_file,
            table_override='links_documentation_615_pp' if is_615 else None,
            contract_number=contract_number_for_links,
        )
