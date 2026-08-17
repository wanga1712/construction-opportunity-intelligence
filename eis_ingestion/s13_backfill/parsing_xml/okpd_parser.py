import os
import xml.etree.ElementTree as ET
import time
import json
from pathlib import Path
from typing import Optional

from utils.logger_config import get_logger
from utils.progress import ProgressManager
from secondary_functions import load_config
from database_work.check_database import DatabaseCheckManager
from database_work.database_id_fetcher import DatabaseIDFetcher
from file_delete.file_deleter import FileDeleter
from parsing_xml.xml_parser import XMLParser
from parsing_xml.xml_parser_recouped_contract import AdvancedXMLParser
from database_work.database_operations import DatabaseOperations

logger = get_logger()

# Путь для отладочных логов (общий для проекта) — используется только для диагностики
DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"


def debug_log(hypothesis_id: str, location: str, message: str, data: Optional[dict] = None) -> None:
    """
    Пишет отладочное сообщение в NDJSON-файл.
    Используется только для диагностики, не влияет на основную логику.
    """
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "sessionId": "debug-session",
            "runId": "okpd-debug",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Никогда не ломаем основную логику из-за проблем с отладочными логами
        pass


def process_okpd_files(folder_path, region_code, progress_manager: Optional[ProgressManager] = None):
    print(f"DEBUG: process_okpd_files called for {folder_path}...", flush=True)
    db_id_fetcher = DatabaseIDFetcher()
    region_id = db_id_fetcher.get_region_id(region_code)

    if not region_id:
        logger.error(f"Не удалось получить ID региона для кода {region_code}")
        print(f"DEBUG: Region ID not found for {region_code}", flush=True)
        return

    config = load_config()
    recouped_contract_archive_44_fz_xml = config.get('path', 'recouped_contract_archive_44_fz_xml', fallback=None)
    recouped_contract_archive_223_fz_xml = config.get('path', 'recouped_contract_archive_223_fz_xml', fallback=None)
    archive_615 = None
    if config.has_section('eis_615'):
        archive_615 = config.get('eis_615', 'archive_xml', fallback=None)

    if folder_path == recouped_contract_archive_44_fz_xml:
        print("DEBUG: Branch process_contract_files", flush=True)
        process_contract_files(folder_path, db_id_fetcher, progress_manager)
    elif folder_path == recouped_contract_archive_223_fz_xml:
        print("DEBUG: Branch process_contract_files (223 recouped)", flush=True)
        process_contract_files(folder_path, db_id_fetcher, progress_manager)
    elif archive_615 and folder_path == archive_615:
        # В XML 615-ПП нет OKPD2 — обходим фильтр ОКПД
        print("DEBUG: Branch process_615_files (OKPD bypass)", flush=True)
        process_615_files(folder_path, region_code, progress_manager)
    else:
        print("DEBUG: Branch process_okpd_files_normal", flush=True)
        process_okpd_files_normal(folder_path, db_id_fetcher, region_code, progress_manager)
    print("DEBUG: process_okpd_files finished.", flush=True)


def process_615_files(folder_path, region_code, progress_manager: Optional[ProgressManager] = None):
    """Обработка XML 615-ПП без фильтрации по ОКПД."""
    config = load_config()
    allowed = set()
    if config.has_section('eis_615'):
        allowed = {
            str(r).strip()
            for r in config.get('eis_615', 'regions', fallback='77,50').split(',')
            if str(r).strip()
        }
    if allowed and str(region_code) not in allowed:
        logger.info(f"615-ПП: регион {region_code} вне allowlist {sorted(allowed)}, пропускаем")
        # Чистим файлы, чтобы не копились
        file_deleter = FileDeleter(folder_path)
        for file_name in [f for f in os.listdir(folder_path) if f.endswith('.xml')]:
            file_deleter.delete_single_file(os.path.join(folder_path, file_name))
        return

    file_deleter = FileDeleter(folder_path)
    xml_files = [f for f in os.listdir(folder_path) if f.endswith(".xml")]
    if not xml_files:
        print("DEBUG: No 615 XML files found.", flush=True)
        return

    total_files = len(xml_files)
    processed_count = 0
    skipped_count = 0
    logger.info(f"615-ПП: найдено {total_files} XML файлов (регион {region_code})")

    xml_parser = XMLParser()
    db_operations = xml_parser.database_operations
    for idx, file_name in enumerate(xml_files, 1):
        file_path = os.path.join(folder_path, file_name)
        try:
            inserted_id = db_operations.insert_file_name(file_name)
            if inserted_id is None:
                file_deleter.delete_single_file(file_path)
                skipped_count += 1
                continue
            # okpd_code=None — в 615 нет ОКПД
            result = xml_parser.parse_xml_tags(file_path, region_code, None, folder_path)
            file_deleter.delete_single_file(file_path)
            if result is None:
                skipped_count += 1
                print(f"DEBUG: 615 skipped {idx}/{total_files}: {file_name}", flush=True)
            else:
                processed_count += 1
                print(f"DEBUG: 615 processed {idx}/{total_files}: {file_name}", flush=True)
        except Exception as e:
            skipped_count += 1
            logger.error(f"615-ПП: ошибка обработки {file_name}: {e}", exc_info=True)
            try:
                file_deleter.delete_single_file(file_path)
            except Exception:
                pass

        if progress_manager and hasattr(progress_manager, "tasks") and "process_all" in getattr(progress_manager, "tasks", {}):
            progress_manager.update_task("process_all", advance=1)
            progress_manager.set_description(
                "process_all",
                f"⚙️ Обработка файлов | Регион {region_code} | 615-ПП | {idx}/{total_files}",
            )

    logger.info(
        f"615-ПП: обработано {processed_count}, ошибок/пропусков {skipped_count} (регион {region_code})"
    )


def process_contract_files(folder_path, db_id_fetcher, progress_manager: Optional[ProgressManager] = None):
    config = load_config()
    recouped_44 = config.get("path", "recouped_contract_archive_44_fz_xml", fallback=None)
    if recouped_44 and folder_path == recouped_44:
        from parsing_xml.rgk_batch import process_44_rgk_folder
        process_44_rgk_folder(folder_path, progress_manager=progress_manager)
        return

    file_deleter = FileDeleter(folder_path)
    xml_files = [f for f in os.listdir(folder_path) if f.endswith(".xml")]
    
    if not xml_files:
        return

    recouped_parser = AdvancedXMLParser(config_path="config.ini")
    db_operations = recouped_parser.database_operations
    
    for file_name in xml_files:
        file_path = os.path.join(folder_path, file_name)
        process_contract_file(
            file_path,
            file_name,
            db_id_fetcher,
            file_deleter,
            folder_path,
            recouped_parser=recouped_parser,
            db_operations=db_operations,
        )


def extract_contract_number_from_filename(file_name: str) -> Optional[str]:
    try:
        base = os.path.basename(file_name)
        if base.startswith("contract_"):
            parts = base.split("_")
            if len(parts) > 1:
                number_part = parts[1]
                if number_part:
                    return number_part
    except Exception:
        pass
    return None


def process_contract_file(
    file_path,
    file_name,
    db_id_fetcher,
    file_deleter,
    folder_path,
    recouped_parser=None,
    db_operations=None,
):
    try:
        # file_id = db_id_fetcher.get_file_names_xml_id(file_name)
        # if file_id:
        #     file_deleter.delete_single_file(file_path)
        #     return

        with open(file_path, "r", encoding="utf-8") as file:
            xml_content = file.read()

        xml_content = XMLParser.remove_namespaces(xml_content)
        root = ET.fromstring(xml_content)

        contract_number = extract_contract_number(root)
        if not contract_number:
            contract_number = extract_contract_number_from_filename(file_name)
        if contract_number:
            result = process_contract_with_number(
                file_path,
                contract_number,
                folder_path,
                recouped_parser=recouped_parser,
            )
            if result != "duplicate_non_target_version":
                ops = db_operations or DatabaseOperations()
                ops.insert_file_name(file_name)
        else:
            logger.error(f"Не найден номер контракта в файле {file_name}")
            try:
                top_level_tags = [child.tag.split("}")[-1] if "}" in child.tag else child.tag for child in root[:5]]
                logger.error(f"Структура XML (первые 5 элементов корня): {top_level_tags}")
            except Exception:
                pass
            file_deleter.delete_single_file(file_path)

    except Exception as e:
        logger.error(f"Ошибка при обработке файла {file_name}: {e}")
        file_deleter.delete_single_file(file_path)


def extract_contract_number(root):
    possible_xpaths = [
        "order/notificationNumber",
        "notificationNumber",
        "contractNumber",
        "contract_number",
        "order/contractNumber",
        "order/contract_number",
        "contract/notificationNumber",
        "contract/contractNumber",
    ]
    
    for xpath in possible_xpaths:
        parts = xpath.split("/")
        element = root
        for part in parts:
            found = None
            for child in element:
                tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag_name == part:
                    found = child
                    break
            
            if found is None:
                found = element.find(f".//{part}")
            
            if found is None:
                break
            element = found
        
        if element is not None and element.text:
            contract_number = element.text.strip()
            if contract_number:
                return contract_number
    
    for elem in root.iter():
        tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if ("notificationNumber" in tag_name.lower() or "contractNumber" in tag_name.lower() or 
            "contract_number" in tag_name.lower()) and elem.text:
            contract_number = elem.text.strip()
            if contract_number:
                return contract_number
    
    return None


def process_contract_with_number(file_path, contract_number, folder_path, recouped_parser=None):
    xml_parser_recouped = recouped_parser or AdvancedXMLParser(config_path="config.ini")
    return xml_parser_recouped.parse_xml_tags_recouped_contract(file_path, contract_number, folder_path)


def process_okpd_files_normal(folder_path, db_id_fetcher, region_code, progress_manager: Optional[ProgressManager] = None):
    print(f"DEBUG: process_okpd_files_normal started for {folder_path}", flush=True)
    file_deleter = FileDeleter(folder_path)
    xml_files = [f for f in os.listdir(folder_path) if f.endswith(".xml")]

    if not xml_files:
        print("DEBUG: No XML files found.", flush=True)
        debug_log(
            "OK1",
            "okpd_parser.py:process_okpd_files_normal",
            "XML файлов не найдено в папке",
            {"folder_path": folder_path, "region_code": region_code},
        )
        return

    total_files = len(xml_files)
    print(f"DEBUG: Found {total_files} XML files.", flush=True)
    processed_count = 0
    skipped_count = 0
    
    logger.info(f"Найдено {total_files} XML файлов для обработки (регион {region_code})")
    debug_log(
        "OK2",
        "okpd_parser.py:process_okpd_files_normal",
        "Найдены XML файлы для обработки",
        {"folder_path": folder_path, "region_code": region_code, "total_files": total_files},
    )
    
    # Используем единый прогресс-бар "process_all" если он существует
    use_unified_progress = False
    if progress_manager and hasattr(progress_manager, 'tasks') and "process_all" in progress_manager.tasks:
        use_unified_progress = True
        fz_type = "44-ФЗ" if "44" in folder_path else "223-ФЗ"
        progress_manager.set_description("process_all", f"⚙️ Обработка файлов | Регион {region_code} | {fz_type} | 0/{total_files}")
    elif progress_manager:
        fz_type = "44-ФЗ" if "44" in folder_path else "223-ФЗ"
        process_task_name = "process_44" if fz_type == "44-ФЗ" else "process_223"
        progress_manager.update_task(process_task_name, advance=0, total=total_files)
        progress_manager.set_description(process_task_name, f"⚙️ Обработка {fz_type} | Регион {region_code} | 0/{total_files}")
    
    xml_parser = XMLParser(config_path="config.ini")
    db_operations = xml_parser.database_operations

    for idx, file_name in enumerate(xml_files, 1):
        print(f"DEBUG: Processing file {idx}/{total_files}: {file_name}", flush=True)
        file_path = os.path.join(folder_path, file_name)
        result = process_okpd_file(
            file_path,
            file_name,
            db_id_fetcher,
            region_code,
            file_deleter,
            folder_path,
            db_operations=db_operations,
            xml_parser=xml_parser,
        )
        print(f"DEBUG: Finished file {idx}/{total_files}: {result}", flush=True)
        
        if result == "processed":
            processed_count += 1
        elif result == "skipped":
            skipped_count += 1
        # Ошибки БД теперь пробрасываются как исключения, не обрабатываются здесь
        
        if progress_manager:
            if use_unified_progress:
                fz_type = "44-ФЗ" if "44" in folder_path else "223-ФЗ"
                progress_manager.update_task("process_all", advance=1)
                progress_manager.set_description("process_all", f"⚙️ Обработка файлов | Регион {region_code} | {fz_type} | {idx}/{total_files}")
            else:
                fz_type = "44-ФЗ" if "44" in folder_path else "223-ФЗ"
                process_task_name = "process_44" if fz_type == "44-ФЗ" else "process_223"
                progress_manager.update_task(process_task_name, advance=1)
                progress_manager.set_description(process_task_name, f"⚙️ Обработка {fz_type} | Регион {region_code} | {idx}/{total_files}")
    
    logger.info(f"Обработано файлов: {processed_count} обработано, {skipped_count} пропущено (регион {region_code})")
    debug_log(
        "OK3",
        "okpd_parser.py:process_okpd_files_normal",
        "Обработка XML файлов завершена",
        {
            "folder_path": folder_path,
            "region_code": region_code,
            "processed_count": processed_count,
            "skipped_count": skipped_count,
            "total_files": total_files,
        },
    )


def process_okpd_file(
    file_path,
    file_name,
    db_id_fetcher,
    region_code,
    file_deleter,
    folder_path,
    db_operations=None,
    xml_parser=None,
):
    """
    Обрабатывает XML файл:
    1. Проверяет в БД, был ли файл уже обработан
    2. Если был - пропускает
    3. Если не был - проверяет ОКПД код
    4. Если ОКПД есть в БД - обрабатывает файл
    5. Если ОКПД нет - пропускает
    
    При ошибке доступа к БД - НЕ обрабатывает файл и НЕ удаляет его (чтобы не потерять данные)
    """
    try:
        debug_log(
            "OK4",
            "okpd_parser.py:process_okpd_file",
            "Начало обработки файла",
            {"file_name": file_name, "region_code": region_code, "folder_path": folder_path},
        )

        # Файл новый - добавляем его имя в БД
        try:
            ops = db_operations or DatabaseOperations()
            inserted_id = ops.insert_file_name(file_name)
            if inserted_id is None:
                try:
                    from utils import stats as stats_collector
                    stats_collector.increment("files_skipped_already_processed", 1)
                except Exception:
                    pass
                file_deleter.delete_single_file(file_path)
                return "skipped"
            debug_log(
                "OK6",
                "okpd_parser.py:process_okpd_file",
                "Новое имя файла добавлено в file_names_xml",
                {"file_name": file_name, "region_code": region_code, "folder_path": folder_path, "inserted_id": inserted_id},
            )
        except Exception as db_error:
            # Ошибка при добавлении имени файла - критическая ошибка БД - пробрасываем исключение дальше
            from utils.exceptions import DatabaseError
            error_msg = f"КРИТИЧЕСКАЯ ОШИБКА: Нет доступа к БД при добавлении файла {file_name}. Ошибка: {db_error}"
            logger.error(error_msg)
            raise DatabaseError(error_msg, original_error=db_error) from db_error
        
        try:
            from utils import stats as stats_collector
            stats_collector.increment("files_processed", 1)
        except Exception:
            pass

        # Читаем и парсим XML
        with open(file_path, "r", encoding="utf-8") as file:
            xml_content = file.read()

        xml_content = XMLParser.remove_namespaces(xml_content)
        root = ET.fromstring(xml_content)

        okpd_code = extract_okpd_code(root)
        if okpd_code:
            # Проверяем ОКПД код в БД и обрабатываем
            try:
                debug_log(
                    "OK7",
                    "okpd_parser.py:process_okpd_file",
                    "Найден ОКПД код в файле",
                    {"file_name": file_name, "region_code": region_code, "okpd_code": okpd_code},
                )
                process_okpd_code(okpd_code, file_path, region_code, folder_path, xml_parser=xml_parser)
                debug_log(
                    "OK8",
                    "okpd_parser.py:process_okpd_file",
                    "Файл обработан с ОКПД и удалён",
                    {"file_name": file_name, "region_code": region_code, "okpd_code": okpd_code},
                )
                return "processed"
            except Exception as db_error:
                # Ошибка при проверке/обработке ОКПД - критическая ошибка БД - пробрасываем исключение дальше
                from utils.exceptions import DatabaseError
                error_msg = f"КРИТИЧЕСКАЯ ОШИБКА: Нет доступа к БД при обработке ОКПД {okpd_code} в файле {file_name}. Ошибка: {db_error}"
                logger.error(error_msg)
                raise DatabaseError(error_msg, original_error=db_error) from db_error
        else:
            # ОКПД код не найден в файле - удаляем файл
            try:
                from utils import stats as stats_collector
                stats_collector.increment("files_skipped_no_okpd", 1)
            except Exception:
                pass
            logger.warning(f"Не найден код ОКПД в файле {file_name}, файл удалён")
            debug_log(
                "OK9",
                "okpd_parser.py:process_okpd_file",
                "ОКПД код не найден в файле, файл удалён",
                {"file_name": file_name, "region_code": region_code},
            )
            file_deleter.delete_single_file(file_path)
            return "skipped"

    except Exception as e:
        # Другие ошибки (не БД) - логируем и удаляем файл
        logger.error(f"Ошибка при обработке файла {file_name}: {e}", exc_info=True)
        debug_log(
            "OK10",
            "okpd_parser.py:process_okpd_file",
            "Ошибка при обработке файла",
            {"file_name": file_name, "region_code": region_code, "error": str(e)},
        )
        file_deleter.delete_single_file(file_path)
        return "error"


def extract_okpd_code(root):
    okpd_code_element = root.find(".//OKPDCode")
    if okpd_code_element is not None:
        return okpd_code_element.text

    okpd2_code_element = root.find(".//okpd2/code")
    if okpd2_code_element is not None:
        return okpd2_code_element.text

    return None


def process_okpd_code(okpd_code, file_path, region_code, folder_path, xml_parser=None):
    """
    Обрабатывает файл с ОКПД кодом:
    1. Проверяет, есть ли ОКПД код в БД (в таблице collection_codes_okpd)
    2. Если есть - обрабатывает файл и удаляет его
    3. Если нет - просто удаляет файл (ОКПД не интересен)
    
    При ошибке БД - выбрасывает исключение (чтобы вызывающий код знал об ошибке)
    """
    print(f"DEBUG: process_okpd_code called for {okpd_code}", flush=True)
    if len(okpd_code.split('.')) == 2 and okpd_code.endswith('0'):
        okpd_code = okpd_code[:-1]

    parser = xml_parser or XMLParser(config_path="config.ini")
    # get_okpd_id теперь выбрасывает исключение при ошибке БД
    print("DEBUG: Checking OKPD in DB...", flush=True)
    exists_in_db = parser.db_id_fetcher.get_okpd_id(okpd_code)
    print(f"DEBUG: OKPD exists in DB: {exists_in_db}", flush=True)
    
    if exists_in_db:
        # ОКПД код есть в БД - обрабатываем файл
        print("DEBUG: Parsing XML tags...", flush=True)
        parser.parse_xml_tags(file_path, region_code, okpd_code, folder_path)
        print("DEBUG: XML tags parsed.", flush=True)

        file_deleter = FileDeleter(folder_path)
        file_deleter.delete_single_file(file_path)
    else:
        # ОКПД код не найден в БД - просто удаляем файл
        print("DEBUG: OKPD not in DB, deleting file...", flush=True)
        file_deleter = FileDeleter(folder_path)
        file_deleter.delete_single_file(file_path)
    print("DEBUG: process_okpd_code finished.", flush=True)
