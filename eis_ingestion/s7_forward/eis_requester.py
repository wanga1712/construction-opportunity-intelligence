from datetime import datetime, timezone
import requests
import time
from typing import Optional

from utils.logger_config import get_logger
from utils.progress import ProgressManager
from utils import XMLParser
from utils import stats as stats_collector
from secondary_functions import load_token, load_config
from database_work.database_requests import get_region_codes
from file_downloader import FileDownloader

logger = get_logger()


class EISRequester:
    def __init__(self, config_path: str = "config.ini", date: Optional[str] = None):
        self.config = load_config(config_path)
        if not self.config:
            raise ValueError("Ошибка загрузки конфигурации!")

        self.url = "http://localhost:8080/eis-integration/services/getDocsIP"
        self.token = load_token(self.config)
        # Если дата передана напрямую, используем её, иначе читаем из конфига
        if date:
            self.date = date
        else:
            self.date = self.config.get("eis", "date")
        self.regions = get_region_codes()
        self.subsystems_44 = [s.strip() for s in self.config.get("eis", "subsystems_44").split(",")]
        # Используем правильные ключи из конфига (с заглавной буквы или без - проверяем оба варианта)
        try:
            self.documentType44_PRIZ = [doc.strip() for doc in self.config.get("eis", "documentType44_PRIZ").split(",")]
        except:
            self.documentType44_PRIZ = [doc.strip() for doc in self.config.get("eis", "documenttype44_priz").split(",")]
        try:
            self.documentType44_RGK = [doc.strip() for doc in self.config.get("eis", "documentType44_RGK").split(",")]
        except:
            self.documentType44_RGK = [doc.strip() for doc in self.config.get("eis", "documenttype44_rgk").split(",")]
        self.subsystems_223 = [s.strip() for s in self.config.get("eis", "subsystems_223").split(",")]
        try:
            self.documentType223_RI223 = [doc.strip() for doc in self.config.get("eis", "documentType223_RI223").split(",")]
        except:
            self.documentType223_RI223 = [doc.strip() for doc in self.config.get("eis", "documenttype223_ri223").split(",")]
        try:
            self.documentType223_RD223 = [doc.strip() for doc in self.config.get("eis", "documentType223_RD223").split(",")]
        except:
            self.documentType223_RD223 = [doc.strip() for doc in self.config.get("eis", "documenttype223_rd223").split(",")]
        
        # 615-ПП конфигурация
        try:
            self._615_enabled = self.config.getboolean('eis_615', 'enabled', fallback=False)
        except Exception:
            self._615_enabled = False
        self._615_regions = set()
        if self._615_enabled:
            self._615_subsystem = self.config.get('eis_615', 'subsystem', fallback='RD615')
            self._615_doctypes = [d.strip() for d in self.config.get('eis_615', 'documenttypes').split(',') if d.strip()]
            # Только Москва и МО по умолчанию
            regions_raw = self.config.get('eis_615', 'regions', fallback='77,50')
            self._615_regions = {str(r).strip() for r in regions_raw.split(',') if str(r).strip()}

        self.xml_parser = XMLParser()
        self.file_downloader = FileDownloader()
        self.progress_manager: Optional[ProgressManager] = None

    def get_current_time_utc(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def generate_soap_request(self, region_code: int, subsystem: str, document_type: str) -> str:
        import uuid
        # Генерация уникального идентификатора для запроса
        id_value = str(uuid.uuid4())
        # Получаем текущее время в формате UTC
        current_time = self.get_current_time_utc()

        # Важно: для RD615/PPRF615 ЕИС тоже ожидает элемент documentType44
        # (documentType615 даёт ошибку валидации схемы, code=28).
        soap_request = f"""<?xml version="1.0" encoding="UTF-8"?>
        <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                          xmlns:ws="http://zakupki.gov.ru/fz44/get-docs-ip/ws">
            <soapenv:Header>
                <individualPerson_token>{self.token}</individualPerson_token>
            </soapenv:Header>
            <soapenv:Body>
                <ws:getDocsByOrgRegionRequest>
                    <index>
                        <id>{id_value}</id>
                        <createDateTime>{current_time}</createDateTime>
                        <mode>PROD</mode>
                    </index>
                    <selectionParams>
                        <orgRegion>{region_code}</orgRegion>
                        <subsystemType>{subsystem}</subsystemType>
                        <documentType44>{document_type}</documentType44>
                        <periodInfo>
                            <exactDate>{self.date}</exactDate>
                        </periodInfo>
                    </selectionParams>
                </ws:getDocsByOrgRegionRequest>
            </soapenv:Body>
        </soapenv:Envelope>
        """
        return soap_request

    def send_soap_request(self, soap_request: str, region_code: int, document_type: str, subsystem: str) -> str:
        """
        Отправляет SOAP-запрос с повторными попытками при ошибках подключения.
        При ошибке подключения повторяет попытку с увеличивающейся паузой: 5, 10, 15... до 60 минут, потом цикл заново.
        """
        headers = {
            "Content-Type": "text/xml",
            "Authorization": f"Bearer {self.token}"
        }
        
        # Начальная пауза и максимальная пауза
        current_pause = 5 * 60  # 5 минут в секундах
        max_pause = 60 * 60  # 60 минут в секундах
        attempt = 0
        
        while True:
            try:
                response = requests.post(self.url, data=soap_request.encode("utf-8"), headers=headers, verify=False, timeout=(10, 120))
                response.raise_for_status()
                return response.text
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                attempt += 1
                error_msg = f"Ошибка подключения (регион {region_code}, {subsystem}, {document_type}): {e}"
                logger.error(error_msg)
                
                # Выводим информацию о попытке переподключения
                pause_minutes = current_pause // 60
                print(f"\n⚠️  Ошибка подключения | Попытка {attempt} | Пауза {pause_minutes} мин | Переподключение...")
                
                # Ждем перед следующей попыткой
                time.sleep(current_pause)
                
                # Увеличиваем паузу на 5 минут, но не больше 60 минут
                current_pause = min(current_pause + 5 * 60, max_pause)
                
                # Если достигли максимума, сбрасываем на 5 минут
                if current_pause >= max_pause:
                    current_pause = 5 * 60
                    print(f"🔄 Цикл пауз сброшен, начинаем с 5 минут")
                
                # Продолжаем цикл для повторной попытки
                continue
            except requests.exceptions.RequestException as e:
                # Для других ошибок (не подключение) просто пробрасываем исключение
                error_msg = f"Ошибка при выполнении SOAP-запроса (регион {region_code}, подсистема {subsystem}, документ {document_type}): {e}"
                logger.error(error_msg, exc_info=True)
                raise

    def process_requests(self, processed_regions=None, on_region_processed=None):
        """
        Обрабатывает запросы к ЕИС для всех регионов.
        
        :param processed_regions: Множество кодов регионов, которые уже обработаны (будут пропущены)
        :param on_region_processed: Callback функция, вызываемая после обработки каждого региона (region_code)
        """
        if processed_regions is None:
            processed_regions = set()
        
        self.progress_manager = ProgressManager()
        self.progress_manager.start()
        
        try:
            # Фильтруем регионы, исключая уже обработанные
            regions_to_process = [r for r in self.regions if r not in processed_regions]
            
            if not regions_to_process:
                logger.info(f"Все регионы для даты {self.date} уже обработаны, пропускаем")
                return
            
            if processed_regions:
                logger.info(f"Пропущено уже обработанных регионов: {len(processed_regions)}, осталось обработать: {len(regions_to_process)}")
                print(f"ℹ️  Пропущено уже обработанных регионов: {len(processed_regions)}, осталось обработать: {len(regions_to_process)}")
            
            total_requests = 0
            for region_code in regions_to_process:
                for subsystem in self.subsystems_44:
                    if subsystem == "PRIZ":
                        total_requests += len(self.documentType44_PRIZ)
                    elif subsystem == "RGK":
                        total_requests += len(self.documentType44_RGK)
                for subsystem in self.subsystems_223:
                    if subsystem == "RI223":
                        total_requests += len(self.documentType223_RI223)
                    elif subsystem == "RD223":
                        total_requests += len(self.documentType223_RD223)
                if self._615_enabled and str(region_code) in self._615_regions:
                    total_requests += len(self._615_doctypes)
            
            # Единый прогресс-бар для всех регионов
            self.progress_manager.add_task("regions", f"🌍 Регионы", total=len(regions_to_process))
            self.progress_manager.add_task("requests", f"📡 Запросы к ЕИС", total=total_requests)
            self.progress_manager.add_task("download_all", f"⬇️ Скачивание архивов", total=None)
            self.progress_manager.add_task("process_all", f"⚙️ Обработка файлов", total=None)
            
            for region_idx, region_code in enumerate(regions_to_process, 1):
                # Обновляем прогресс регионов
                self.progress_manager.update_task("regions", advance=1)
                self.progress_manager.set_description("regions", f"🌍 Регионы | {region_idx}/{len(self.regions)}")
                
                # Снимок статистики ДО обработки региона
                stats_before = stats_collector.get_snapshot()
                downloaded_archives = 0  # Счетчик скачанных архивов для региона
                
                for subsystem in self.subsystems_44:
                    document_types = []
                    if subsystem == "PRIZ":
                        document_types = self.documentType44_PRIZ
                    elif subsystem == "RGK":
                        document_types = self.documentType44_RGK
                    
                    # Обновляем описание только при смене подсистемы
                    self.progress_manager.set_description("requests", f"📡 Запросы к ЕИС | Регион {region_code} | {subsystem}")
                    
                    for doc_type in document_types:
                        # НЕ переходим к следующему запросу пока не обработаем текущий
                        # send_soap_request сам будет повторять попытки при ошибках подключения
                        self.progress_manager.update_task("requests", advance=1)
                        
                        soap_request = self.generate_soap_request(region_code, subsystem, doc_type)
                        # send_soap_request будет повторять попытки при ошибках подключения до успеха
                        response_xml = self.send_soap_request(soap_request, region_code, doc_type, subsystem)
                        archive_urls = self.xml_parser.extract_archive_urls(response_xml)
                        
                        if archive_urls:
                            downloaded_archives += len(archive_urls)
                            # Скачиваем и сразу обрабатываем
                            self.file_downloader.download_files(archive_urls, subsystem, region_code, self.progress_manager)
                        
                        time.sleep(0.5)
                
                for subsystem in self.subsystems_223:
                    document_types = []
                    if subsystem == "RI223":
                        document_types = self.documentType223_RI223
                    elif subsystem == "RD223":
                        document_types = self.documentType223_RD223
                    
                    # Обновляем описание только при смене подсистемы
                    self.progress_manager.set_description("requests", f"📡 Запросы к ЕИС | Регион {region_code} | {subsystem}")
                    
                    for doc_type in document_types:
                        # НЕ переходим к следующему запросу пока не обработаем текущий
                        # send_soap_request сам будет повторять попытки при ошибках подключения
                        self.progress_manager.update_task("requests", advance=1)
                        
                        soap_request = self.generate_soap_request(region_code, subsystem, doc_type)
                        # send_soap_request будет повторять попытки при ошибках подключения до успеха
                        response_xml = self.send_soap_request(soap_request, region_code, doc_type, subsystem)
                        archive_urls = self.xml_parser.extract_archive_urls(response_xml)
                        
                        if archive_urls:
                            downloaded_archives += len(archive_urls)
                            # Скачиваем и сразу обрабатываем
                            self.file_downloader.download_files(archive_urls, subsystem, region_code, self.progress_manager)
                        
                        time.sleep(0.5)
                
                # 615-ПП проход — только выбранные регионы (Москва/МО)
                if self._615_enabled and str(region_code) in self._615_regions:
                    self.progress_manager.set_description("requests", f"📡 Запросы к ЕИС | Регион {region_code} | {self._615_subsystem} (615-ПП)")
                    for doc_type in self._615_doctypes:
                        self.progress_manager.update_task("requests", advance=1)
                        soap_request = self.generate_soap_request(region_code, self._615_subsystem, doc_type)
                        response_xml = self.send_soap_request(soap_request, region_code, doc_type, self._615_subsystem)
                        archive_urls = self.xml_parser.extract_archive_urls(response_xml)
                        if archive_urls:
                            downloaded_archives += len(archive_urls)
                            self.file_downloader.download_files(archive_urls, f"615_{self._615_subsystem}", region_code, self.progress_manager)
                        time.sleep(0.5)

                # Снимок статистики ПОСЛЕ обработки региона
                stats_after = stats_collector.get_snapshot()
                
                # Вычисляем дельту (что добавилось за этот регион)
                region_stats = {}
                for key in stats_after:
                    before_value = stats_before.get(key, 0)
                    after_value = stats_after.get(key, 0)
                    delta = after_value - before_value
                    if delta > 0:
                        region_stats[key] = delta
                
                # Выводим статистику по региону
                if downloaded_archives > 0 or region_stats:
                    parts = []
                    if downloaded_archives > 0:
                        parts.append(f"📥 Скачано архивов: {downloaded_archives}")
                    if region_stats:
                        db_parts = []
                        # Маппинг ключей на русские названия
                        ru_labels = {
                            'customer': 'Заказчиков',
                            'contractor': 'Подрядчиков',
                            'reestr_contract_44_fz': 'Торгов 44-ФЗ',
                            'reestr_contract_223_fz': 'Торгов 223-ФЗ',
                            'links_documentation_44_fz': 'Ссылок 44-ФЗ',
                            'links_documentation_223_fz': 'Ссылок 223-ФЗ',
                            'trading_platform': 'Торговых площадок',
                        }
                        for key, value in region_stats.items():
                            label = ru_labels.get(key, key)
                            db_parts.append(f"{label}: {value}")
                        if db_parts:
                            parts.append(f"💾 В БД: {', '.join(db_parts)}")
                    
                    if parts:
                        print(f"\r{' '*100}\r✅ Регион {region_code} ({region_idx}/{len(regions_to_process)}): {' | '.join(parts)}", flush=True)
                
                # Сохраняем прогресс обработки региона
                if on_region_processed:
                    try:
                        on_region_processed(region_code)
                    except Exception as e:
                        logger.error(f"Ошибка при сохранении прогресса региона {region_code}: {e}", exc_info=True)
        finally:
            self.progress_manager.stop()
