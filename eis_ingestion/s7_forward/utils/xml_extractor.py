"""
Утилиты для извлечения данных из XML.
"""
from lxml import etree
from xml.etree import ElementTree as ET

from utils.logger_config import get_logger

# Получаем logger (только ошибки в файл)
logger = get_logger()



def clean_archive_url(url: str) -> str:
    """Убирает хвосты CDATA/мусор из URL архива ЕИС."""
    if not url:
        return url
    u = url.strip()
    # частый хвост из XML CDATA: ]]>
    if u.endswith("]]>"):
        u = u[:-3]
    u = u.rstrip("]>").strip()
    # срезать мусор после пробела
    if " " in u:
        u = u.split(" ", 1)[0]
    return u

class XMLParser:
    """Класс для извлечения URL архивов из XML ответов ЕИС."""
    
    @staticmethod
    def extract_archive_urls(xml_content):
        """
        Извлекает все URL-адреса архивов из XML-строки.

        :param xml_content: Строка, содержащая XML-документ.
        :return: Список URL-адресов архивов, найденных в XML. Если ошибка при парсинге — пустой список.
        """
        try:
            if not xml_content:
                return []

            # Используем lxml для поиска всех элементов <archiveUrl> в XML
            tree = etree.fromstring(xml_content.encode("utf-8"))
            
            # Пробуем разные варианты XPath для поиска архивов
            urls = []
            
            # Вариант 1: простой поиск без namespace
            urls = [url.text for url in tree.xpath("//archiveUrl") if url.text]
            
            # Если не нашли, пробуем с namespace
            if not urls:
                # Ищем все возможные namespace
                namespaces = tree.nsmap if hasattr(tree, 'nsmap') else {}
                
                # Пробуем разные варианты с namespace
                for prefix, uri in namespaces.items():
                    try:
                        xpath = f"//{{{uri}}}archiveUrl"
                        found = [url.text for url in tree.xpath(xpath) if url.text]
                        if found:
                            urls.extend(found)
                    except Exception:
                        pass
                
                # Пробуем без префикса namespace
                try:
                    xpath = "//*[local-name()='archiveUrl']"
                    found = [url.text for url in tree.xpath(xpath) if url.text]
                    if found:
                        urls.extend(found)
                except Exception:
                    pass
            
            # Убираем дубликаты
            urls = list(set(urls))
            
            return urls
        except etree.XMLSyntaxError as e:
            # Логируем ошибку, если произошла ошибка при парсинге XML
            error_msg = f"Ошибка при парсинге XML (XMLSyntaxError): {e}"
            logger.error(error_msg, exc_info=True)
            return []  # Возвращаем пустой список в случае ошибки
        except Exception as e:
            # Логируем любую другую ошибку
            error_msg = f"Неизвестная ошибка при парсинге XML: {e}"
            logger.error(error_msg, exc_info=True)
            return []  # Возвращаем пустой список в случае ошибки

