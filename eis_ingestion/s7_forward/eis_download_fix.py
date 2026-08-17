"""Хелпер: скачивание архивов ЕИС через CryptoPro stunnel."""
from urllib.parse import urlparse, urlunparse


def rewrite_eis_url_via_stunnel(url: str) -> str:
    """https://int.zakupki.gov.ru/... -> http://localhost:8080/..."""
    if not url:
        return url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host in ("int.zakupki.gov.ru", "zakupki.gov.ru"):
        return urlunparse(("http", "localhost:8080", p.path, p.params, p.query, p.fragment))
    return url
