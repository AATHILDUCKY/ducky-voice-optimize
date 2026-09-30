from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from .audio import enhance_file, separate_vocals


class EnhanceWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source: Path, destination: Path, settings: dict, model_dir: Path):
        super().__init__()
        self.source = source
        self.destination = destination
        self.settings = settings
        self.model_dir = model_dir

    @pyqtSlot()
    def run(self) -> None:
        try:
            enhance_file(
                self.source,
                self.destination,
                self.settings,
                self.model_dir,
                self.progress.emit,
            )
            self.finished.emit(str(self.destination))
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class SeparateWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        source: Path,
        vocals: Path,
        background: Path,
        model_dir: Path,
    ):
        super().__init__()
        self.source = source
        self.vocals = vocals
        self.background = background
        self.model_dir = model_dir

    @pyqtSlot()
    def run(self) -> None:
        try:
            separate_vocals(
                self.source,
                self.vocals,
                self.background,
                self.model_dir,
                self.progress.emit,
            )
            self.finished.emit(str(self.vocals), str(self.background))
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))
