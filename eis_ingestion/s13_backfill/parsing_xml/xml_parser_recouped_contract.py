import os
import re
import hashlib
from collections import OrderedDict
import xml.etree.ElementTree as ET

from utils.logger_config import get_logger
from database_work.check_database import DatabaseCheckManager
from database_work.database_operations import DatabaseOperations
from database_work.database_id_fetcher import DatabaseIDFetcher
from database_work.recouped_contract_sync import RecoupedContractSync
from parsing_xml.xml_parser import XMLParser  # Импортируем родительский класс
from file_delete.file_deleter import FileDeleter

# Получаем logger (только ошибки в файл)
logger = get_logger()

_NON_TARGET_VERSION_CACHE_MAX = 100_000
_non_target_version_cache = OrderedDict()


def _non_target_version_key(contract_number: str, cleaned_xml: str) -> str:
    digest = hashlib.sha256(cleaned_xml.encode("utf-8")).hexdigest()
    return f"{contract_number}:{digest}"


def _remember_non_target_version(key: str) -> None:
    _non_target_version_cache[key] = None
    _non_target_version_cache.move_to_end(key)
    while len(_non_target_version_cache) > _NON_TARGET_VERSION_CACHE_MAX:
        _non_target_version_cache.popitem(last=False)


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def extract_rgk_okpd_codes(root) -> list:
    """All OKPD2/code values from RGK XML (item-level preserved, order kept)."""
    codes = []
    seen = set()
    for e in root.iter():
        if _local(e.tag) != "OKPD2":
            continue
        for child in list(e):
            if _local(child.tag) == "code" and child.text and child.text.strip():
                code = child.text.strip()
                if code not in seen:
                    seen.add(code)
                    codes.append(code)
    return codes


def extract_rgk_contract_subject(root) -> str | None:
    for e in root.iter():
        if _local(e.tag) == "contractSubject" and e.text and e.text.strip():
            return e.text.strip()
    return None


class AdvancedXMLParser(XMLParser):
    """
    Дочерний класс, который наследует XMLParser и расширяет его функциональность.
    """

    def __init__(self, config_path="config.ini"):

        super().__init__(config_path)  # Инициализируем родительский класс XMLParser
        self.database_check_manager = DatabaseCheckManager()  # Менеджер для проверки БД
        self._recouped_sync = RecoupedContractSync(self.database_operations.db_manager)

    def _enrich_rgk_okpd_and_subject(self, root, found_tags: dict) -> dict:
        """Attach OKPD2 codes + subject; resolve okpd_id via collection_codes_okpd.

        Multi-OKPD rule: preserve full list in okpd_codes; canonical okpd_id =
        first code that exists in collection_codes_okpd (XML order). Never invent.
        """
        codes = extract_rgk_okpd_codes(root)
        subject = extract_rgk_contract_subject(root)
        if subject and not found_tags.get("auction_name"):
            found_tags["auction_name"] = subject
        elif subject:
            # Prefer real subject over placeholder / sparse tag scrape
            title = str(found_tags.get("auction_name") or "")
            if not title or title.startswith("Контракт "):
                found_tags["auction_name"] = subject

        found_tags["okpd_codes"] = codes
        found_tags["okpd_codes_list"] = codes
        if codes and not found_tags.get("okpd_code"):
            found_tags["okpd_code"] = codes[0]

        okpd_id = None
        chosen = None
        for code in codes:
            try:
                okpd_id = self.db_id_fetcher.get_okpd_id(code)
            except Exception:
                okpd_id = None
            if okpd_id:
                chosen = code
                break
        found_tags["okpd_id"] = okpd_id
        if chosen:
            found_tags["okpd_code"] = chosen
        return found_tags

    def parse_reestr_contract_44_fz_recouped(self, root, tags, id_contract_number, contractor_id, tags_file, contract_number_param=None, known_location=None):
        """
        Парсит RGK/recouped 44-ФЗ и синхронизирует реестр.

        Ищет контракт во всех таблицах (awarded первым), обновляет подрядчика/даты,
        при необходимости переносит unknown/unclear/main/commission → awarded.
        """
        found_tags = {}

        for tag, xpath in tags.items():
            tag_without_namespace = xpath.split(":")[-1]
            elements = root.findall(f".//{tag_without_namespace}")
            if elements:
                values = [elem.text.strip() for elem in elements if elem.text and elem.text.strip()]
                found_tags[tag] = values[0] if values else None
            else:
                found_tags[tag] = None

        found_tags["contractor_id"] = contractor_id

        end_dates = root.findall(".//executionPeriod/endDate")
        if end_dates:
            last_end_date = end_dates[-1].text.strip() if end_dates[-1].text else None
            found_tags["delivery_end_date"] = last_end_date
        else:
            found_tags["delivery_end_date"] = None

        start_dates = root.findall(".//executionPeriod/startDate")
        if start_dates and not found_tags.get("delivery_start_date"):
            first_start = start_dates[0].text.strip() if start_dates[0].text else None
            found_tags["delivery_start_date"] = first_start

        found_tags = self._enrich_rgk_okpd_and_subject(root, found_tags)

        try:
            sync = self._recouped_sync
            number = found_tags.get("contract_number") or contract_number_param
            if not number:
                logger.debug("Recouped 44: нет contract_number в XML, использую fallback из параметра")
                return None

            location = sync.apply_update(
                contract_number=number,
                fields=found_tags,
                fz_type="44",
                known_location=known_location,
                location_lookup_done=True,
            )
            return location.record_id if location else None
        except Exception as e:
            logger.error(f"Ошибка sync контракта 44 в реестре: {e}")
            raise

    def parse_reestr_contract_223_fz_recouped(self, root, tags, contractor_id, contract_number_param=None):
        """Sync recouped 223: поиск включая awarded, update, promote."""
        found_tags = {}
        for tag, xpath in tags.items():
            tag_without_namespace = xpath.split(":")[-1]
            elements = root.findall(f".//{tag_without_namespace}")
            if elements:
                values = [elem.text.strip() for elem in elements if elem.text and elem.text.strip()]
                found_tags[tag] = values[0] if values else None
            else:
                found_tags[tag] = None

        found_tags["contractor_id"] = contractor_id

        found_tags = self._enrich_rgk_okpd_and_subject(root, found_tags)

        number = found_tags.get("contract_number") or contract_number_param
        if not number:
            logger.debug("Recouped 223: нет contract_number в XML, использую fallback из параметра")
            return None
        try:
            location = self._recouped_sync.apply_update(number, found_tags, fz_type="223")
            return location.record_id if location else None
        except Exception as e:
            logger.error(f"Ошибка sync контракта 223: {e}")
            raise

    def parse_contractor(self, root, tags, tags_file):
        """
        Парсит данные для таблицы contractor, проверяя наличие ИНН в базе данных.
        Если ИНН существует, получаем его ID, если нет — добавляем нового поставщика и получаем его ID.
        """
        found_tags = {}

        # Проходим по всем тегам
        for tag, xpath in tags.items():
            element = root.find(f".//{xpath}")
            if element is None:
                found_tags[tag] = None
                continue

            try:
                if tags_file in (self.tags_paths.get('get_tags_44_recouped'), self.tags_paths.get('get_tags_223_recouped')):
                    found_tags[tag] = element.text.strip() if element.text else None
                else:
                    logger.error(f"Неизвестный файл тегов: {tags_file}")
                    return None
            except AttributeError:
                logger.error(f"Ошибка при обработке тега '{tag}': element.text = {element.text}")
                found_tags[tag] = None

        # Проверка наличия ИНН
        inn = found_tags.get('inn')
        if inn:
            contractor_id = self.db_id_fetcher.get_contractor_id(inn)
            if not contractor_id:
                contractor_id = self.database_operations.insert_contractor(found_tags)
                if not contractor_id:
                    logger.error(f"Не удалось добавить нового поставщика с ИНН {inn}")
        else:
            contractor_id = None  # ИНН поставщика необязателен

        return contractor_id

    def parse_links_documentation_recouped(self, root, id_contract_number, links_documentation_tags, tags_file, contract_number=None):
        """
        Универсальный метод: загружает теги из JSON-файла и парсит XML.
        """
        found_tags = []

        for tag_name, tag_data in links_documentation_tags.items():
            xpath = tag_data.get("xpath")
            if not xpath:
                logger.error(f"Отсутствует xpath в секции {tag_name}")
                continue

            for elem in root.findall(xpath):
                file_name_tag = tag_data.get("file_name", tag_data.get("default_file_name", tag_name))
                file_name_elem = elem.find(file_name_tag)
                url_elem = elem.find(tag_data.get("document_links"))

                file_name = file_name_elem.text.strip() if file_name_elem is not None and file_name_elem.text else file_name_tag
                url = url_elem.text.strip() if url_elem is not None and url_elem.text else None

                if url:
                    found_tags.append({
                        "file_name": file_name,
                        "document_links": url,
                        "contract_id": id_contract_number,
                        "contract_number": contract_number,
                    })

        for entry in found_tags:
            try:
                inserted_id = self.database_operations.insert_link_documentation_44_fz(entry)
                if not inserted_id:
                    logger.debug(
                        f"Ссылка пропущена: родительский контракт {entry['contract_id']} "
                        "не находится в основном реестре 44-ФЗ"
                    )
            except Exception as e:
                logger.error(f"Ошибка при вставке в базу (контракт {entry['contract_id']}): {e}", exc_info=True)
                raise

        return found_tags

    def parse_xml_tags_recouped_contract(self, file_path, contract_number, xml_folder_path):
        """
        Функция для извлечения тегов для одной записи XML.
        """

        # Определяем, какой JSON файл использовать в зависимости от папки
        if xml_folder_path == self.xml_paths['recouped_contract_archive_44_fz_xml']:
            tags_file = self.tags_paths['get_tags_44_recouped']
        elif xml_folder_path == self.xml_paths['recouped_contract_archive_223_fz_xml']:
            tags_file = self.tags_paths['get_tags_223_recouped']
        else:
            logger.error(f"Неизвестная папка: {xml_folder_path}")
            raise ValueError(f"Неизвестная папка: {xml_folder_path}")  # Прекращаем выполнение программы

        # Загружаем теги из соответствующего JSON файла
        tags = self.load_json_tags(tags_file)

        if not tags:
            logger.error("Не удалось загрузить теги из JSON.")
            raise ValueError("Не удалось загрузить теги из JSON.")  # Прекращаем выполнение программы

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
            raise  # Прекращаем выполнение программы

        sync = self._recouped_sync
        location = None

        # 44-FZ RGK only. Exact-version dedup is content-based, so the same
        # content under another filename is still recognized. A new version
        # of the same contract is always re-evaluated.
        if tags_file == self.tags_paths['get_tags_44_recouped']:
            codes = extract_rgk_okpd_codes(root)
            version_key = _non_target_version_key(str(contract_number), cleaned_xml_content)
            if version_key in _non_target_version_cache:
                from utils import stats as stats_collector
                stats_collector.increment("rgk_duplicate_version_skipped", 1)
                return "duplicate_non_target_version"

            target_okpd_present = any(
                self.db_id_fetcher.get_okpd_id(code) is not None for code in codes
            )
            location = sync.find_44_one_query(str(contract_number))
            if codes and not target_okpd_present and location is None:
                fields = {
                    "contract_number": str(contract_number),
                    "notification_number": str(contract_number),
                    "auction_name": extract_rgk_contract_subject(root),
                    "okpd_codes": codes,
                    "okpd_codes_list": codes,
                    "okpd_code": codes[0],
                    "raw_file": os.path.basename(file_path),
                }
                sync.record_non_target_once(str(contract_number), fields)
                _remember_non_target_version(version_key)
                from utils import stats as stats_collector
                stats_collector.increment("rgk_non_target_skipped", 1)
                return "new_non_target_version"
        else:
            # 223-FZ behavior is intentionally unchanged in this WIP.
            location = sync.find(str(contract_number))

        # Existing contracts and all target/no-code XML keep normal parsing.
        contractor_id = self.parse_contractor(root, tags.get('contractor', {}), tags_file)
        id_contract_number = location.record_id if location else None
        contract_id = None


        # Выбираем правильную функцию для контракта
        if tags_file == self.tags_paths['get_tags_44_recouped']:
            contract_id = self.parse_reestr_contract_44_fz_recouped(
                root,
                tags.get('reestr_contract', {}),
                id_contract_number,
                contractor_id,
                tags_file,
                contract_number_param=str(contract_number) if contract_number else None,
                known_location=location,
            )
        elif tags_file == self.tags_paths.get('get_tags_223_recouped'):
            contract_id = self.parse_reestr_contract_223_fz_recouped(
                root,
                tags.get('reestr_contract', {}),
                contractor_id,
                contract_number_param=str(contract_number) if contract_number else None,
            )
        elif tags_file == self.tags_paths.get('get_tags_223_new'):
            # Старые «new» 223 recouped без обработки — удаляем файл
            file_deleter = FileDeleter(xml_folder_path)
            file_deleter.delete_single_file(file_path)

        links_documentation = self.parse_links_documentation_recouped(
            root,
            contract_id or id_contract_number,
            tags.get("links_documentation", {}),
            tags_file,
            contract_number=str(contract_number) if contract_number else None,
        )
        return contract_id
