import os
from loguru import logger


class FileDeleter:
    """
    Класс для удаления файлов в указанной папке.
    """

    def __init__(self, folder_path):
        """
        Инициализирует объект для удаления файлов в указанной папке.

        :param folder_path: Путь к папке, из которой будут удаляться файлы
        """
        self.folder_path = folder_path

    def delete_files_in_folder(self):
        """
        Удаляет все файлы в указанной папке.

        :return: Список удалённых файлов
        """
        deleted_files = []

        # Проверка существования папки
        if not os.path.exists(self.folder_path):
            print(f"Папка {self.folder_path} не существует.")
            return deleted_files

        # Перебор файлов в папке и удаление
        for file_name in os.listdir(self.folder_path):
            file_path = os.path.join(self.folder_path, file_name)
            if os.path.isfile(file_path):  # Убедимся, что это файл
                os.remove(file_path)
                deleted_files.append(file_name)  # Добавляем удалённые файлы в список

        return deleted_files

    def delete_single_file(self, file_path):
        """
        Удаляет конкретный файл.

        :param file_path: Путь к файлу, который нужно удалить
        """
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        else:
            return False

    def delete_zip_files_in_folder(self, file_name):
        """
        Удаляет указанный файл с расширением .zip в указанной папке.

        :param file_name: Имя файла, который нужно удалить.
        :return: Список удалённых файлов
        """
        deleted_files = []

        # Логирование перед проверкой существования папки
        logger.info(f"Проверка папки: {self.folder_path}")

        # Проверка существования папки
        if not os.path.exists(self.folder_path):
            logger.error(f"Папка {self.folder_path} не существует.")
            return deleted_files

        logger.info(f"Папка {self.folder_path} существует.")

        # Перебор файлов в папке и удаление .zip файлов
        for file in os.listdir(self.folder_path):
            file_path = os.path.join(self.folder_path, file)
            if os.path.isfile(file_path) and file.lower().endswith('.zip'):
                logger.info(f"Обнаружен файл: {file} в папке {self.folder_path}")
                if file == file_name:  # Удаляем только указанный файл
                    os.remove(file_path)
                    deleted_files.append(file)  # Добавляем удалённый файл в список
                    logger.info(f"Удалён файл: {file}")

        # Логирование итогового результата
        if not deleted_files:
            logger.info("Не было найдено .zip файлов для удаления.")
        else:
            logger.info(f"Удалены следующие .zip файлы: {deleted_files}")

        return deleted_files


