"""
Модуль для управления прогресс-барами в консоли.
"""
import sys
import os
from typing import Optional, Dict
from threading import Lock

PROGRESS_MODE = "simple" # Force simple mode to prevent rich from capturing stdout
# PROGRESS_MODE = os.getenv("PROGRESS_MODE", "simple").lower()

if PROGRESS_MODE == "rich":
    try:
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
        from rich.console import Console
        RICH_AVAILABLE = True
    except ImportError:
        RICH_AVAILABLE = False
        PROGRESS_MODE = "simple"
else:
    RICH_AVAILABLE = False


class _SimpleProgressBackend:
    def __init__(self):
        self.tasks: Dict[str, dict] = {}
        self.lock = Lock()
        self.last_output = {}
    
    def add_task(self, name: str, description: str, total: Optional[int] = None) -> str:
        with self.lock:
            self.tasks[name] = {
                "description": description,
                "total": total,
                "completed": 0,
                "started": False
            }
        return name
    
    def update(self, task_id: str, advance: int = 0, description: Optional[str] = None, total: Optional[int] = None):
        with self.lock:
            if task_id not in self.tasks:
                return
            
            task = self.tasks[task_id]
            
            # Обновляем счетчик только если advance > 0
            if advance > 0:
                task["completed"] = task.get("completed", 0) + advance
            
            # Обновляем описание только если оно изменилось
            if description and description != task.get("description"):
                task["description"] = description
            
            if total is not None:
                task["total"] = total
            
            # Выводим прогресс только если он изменился (каждые 10 обновлений или при изменении описания)
            completed = task["completed"]
            total_val = task["total"]
            
            # Обновляем вывод только при значимых изменениях (каждые 5% или при изменении описания)
            should_update = False
            if description and description != task.get("last_printed_desc"):
                should_update = True
                task["last_printed_desc"] = description
            elif total_val and total_val > 0:
                # Обновляем каждые 5% прогресса
                last_percent = task.get("last_percent", -1)
                current_percent = int((completed / total_val) * 5) * 5  # Округляем до 5%
                if current_percent != last_percent:
                    should_update = True
                    task["last_percent"] = current_percent
            elif completed % 10 == 0:  # Для неопределенного прогресса обновляем каждые 10
                should_update = True
            
            if should_update:
                desc = task["description"]
                if total_val and total_val > 0:
                    percent = int((completed / total_val) * 100)
                    # Создаем визуальную полоску прогресса
                    bar_width = 30
                    filled = int(bar_width * completed / total_val)
                    bar = "█" * filled + "░" * (bar_width - filled)
                    progress_str = f"{desc} | [{bar}] {percent}% ({completed}/{total_val})"
                else:
                    progress_str = f"{desc} | {completed}"
                
                # Используем \r для обновления строки, но добавляем пробелы для очистки
                print(f"\r{progress_str:<120}", end="", flush=True)
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        print()


class ProgressManager:
    def __init__(self):
        self.tasks: Dict[str, str] = {}
        self.progress = None
        self.console = None
        
        # Используем Rich если явно указано или если доступен и это терминал
        # В PyCharm тоже пытаемся использовать Rich с force_terminal=True
        use_rich = PROGRESS_MODE == "rich" and RICH_AVAILABLE
        
        if use_rich:
            self.console = Console(force_terminal=True, soft_wrap=False, width=120)
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=None),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("[bold blue]{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self.console,
                expand=True
            )
        else:
            self.progress = _SimpleProgressBackend()
    
    def start(self) -> None:
        if hasattr(self.progress, "__enter__"):
            self.progress.__enter__()
    
    def stop(self) -> None:
        if hasattr(self.progress, "__exit__"):
            self.progress.__exit__(None, None, None)
    
    def add_task(self, name: str, description: str, total: Optional[int] = None) -> str:
        if name in self.tasks:
            return self.tasks[name]
        
        if isinstance(self.progress, _SimpleProgressBackend):
            task_id = self.progress.add_task(name, description, total=total)
        else:
            task_id = self.progress.add_task(description, total=total)
        
        self.tasks[name] = task_id
        return task_id
    
    def update_task(self, name: str, advance: int = 0, total: Optional[int] = None, description: Optional[str] = None) -> None:
        if name not in self.tasks:
            return
        
        task_id = self.tasks[name]
        
        if isinstance(self.progress, _SimpleProgressBackend):
            self.progress.update(task_id, advance=advance, description=description, total=total)
        else:
            update_params = {"advance": advance}
            if description:
                update_params["description"] = description
            if total is not None:
                update_params["total"] = total
            self.progress.update(task_id, **update_params)
    
    def set_description(self, name: str, description: str) -> None:
        if name not in self.tasks:
            return
        
        task_id = self.tasks[name]
        
        if isinstance(self.progress, _SimpleProgressBackend):
            self.progress.update(task_id, description=description)
        else:
            self.progress.update(task_id, description=description)
    
    def reset_task(self, name: str, total: Optional[int] = None) -> None:
        if name not in self.tasks:
            return
        
        task_id = self.tasks[name]
        
        if isinstance(self.progress, _SimpleProgressBackend):
            if task_id in self.progress.tasks:
                current_completed = self.progress.tasks[task_id].get("completed", 0)
                self.progress.update(task_id, advance=-current_completed, total=total)
        else:
            self.progress.reset(task_id, total=total)

