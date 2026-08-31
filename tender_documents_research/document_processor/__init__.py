def __getattr__(name: str):
    if name == "QueueManager":
        from .queue_manager import QueueManager
        return QueueManager
    if name == "Downloader":
        from .downloader import Downloader
        return Downloader
    if name == "ParserFactory":
        from .parser_factory import ParserFactory
        return ParserFactory
    if name == "KeywordMatcher":
        from .matcher import KeywordMatcher
        return KeywordMatcher
    if name == "DocumentProcessorDaemon":
        from .daemon import DocumentProcessorDaemon
        return DocumentProcessorDaemon
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    "QueueManager",
    "Downloader",
    "ParserFactory",
    "KeywordMatcher",
    "DocumentProcessorDaemon",
]

