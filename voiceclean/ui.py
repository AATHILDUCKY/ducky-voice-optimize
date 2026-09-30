from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QThread, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPen
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .audio import Recorder, audio_info, waveform_peaks
from .database import Database, Project
from .styles import STYLE
from .workers import EnhanceWorker, SeparateWorker


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class DropZone(QFrame):
    file_dropped = pyqtSignal(str)
    clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(128)
        self.setStyleSheet(
            "QFrame {background:#0d151f; border:1px dashed #3b4c63; border-radius:12px;}"
            "QFrame:hover {background:#101b28; border-color:#6c8bff;}"
            "QLabel {border:none; background:transparent;}"
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("＋")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size:28px;color:#7894ff")
        title = QLabel("Drop an audio file here")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight:700;color:#e8eef7")
        hint = QLabel("or click to browse · WAV, FLAC, OGG, MP3*")
        hint.setObjectName("Subtle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(hint)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.file_dropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()


class Waveform(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._peaks = np.array([], dtype=np.float32)
        self._progress = 0.0

    def set_audio(self, path: str | None) -> None:
        try:
            self._peaks = waveform_peaks(path) if path else np.array([], dtype=np.float32)
        except Exception:
            self._peaks = np.array([], dtype=np.float32)
        self._progress = 0.0
        self.update()

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 10, -10, -10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0b131d"))
        painter.drawRoundedRect(rect, 10, 10)
        mid = rect.center().y()
        painter.setPen(QPen(QColor("#1e2a39"), 1))
        painter.drawLine(rect.left(), mid, rect.right(), mid)

        if self._peaks.size == 0:
            painter.setPen(QColor("#5f7085"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Your waveform will appear here")
            return
        maximum = max(float(np.max(np.abs(self._peaks))), 1e-5)
        step = rect.width() / max(1, len(self._peaks) - 1)
        half_height = rect.height() * 0.39
        played_x = rect.left() + rect.width() * self._progress
        for index, peak in enumerate(np.abs(self._peaks)):
            x = rect.left() + index * step
            amplitude = max(1.5, float(peak) / maximum * half_height)
            color = QColor("#6c8bff") if x <= played_x else QColor("#34445a")
            painter.setPen(QPen(color, max(1.0, step * 0.7), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(x), int(mid - amplitude), int(x), int(mid + amplitude))


class LabeledSlider(QWidget):
    changed = pyqtSignal()

    def __init__(self, title: str, minimum: int, maximum: int, value: int, suffix: str):
        super().__init__()
        self.suffix = suffix
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.title = QLabel(title)
        self.value_label = QLabel()
        self.value_label.setObjectName("Metric")
        row.addWidget(self.title)
        row.addStretch()
        row.addWidget(self.value_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._update)
        layout.addLayout(row)
        layout.addWidget(self.slider)
        self._update()

    def _update(self) -> None:
        prefix = "+" if self.suffix == " dB" and self.slider.value() > 0 else ""
        self.value_label.setText(f"{prefix}{self.slider.value()}{self.suffix}")
        self.changed.emit()

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.setValue(value)


class MainWindow(QMainWindow):
    def __init__(self, database: Database, projects_root: Path):
        super().__init__()
        self.database = database
        self.projects_root = projects_root
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.models_root = projects_root.parent / "models"
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.current_project: Project | None = None
        self.recorder = Recorder()
        self.record_started_at = 0.0
        self.worker_thread: QThread | None = None
        self.worker: EnhanceWorker | SeparateWorker | None = None
        self.playing_kind = "source"
        self.enhance_target = "output"
        self.active_enhancement_mode = "fast"

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self._playback_position)
        self.player.durationChanged.connect(self._playback_position)
        self.player.playbackStateChanged.connect(self._playback_state)

        self.record_timer = QTimer(self)
        self.record_timer.setInterval(100)
        self.record_timer.timeout.connect(self._update_record_time)

        self.setWindowTitle("Ducky Voice Optimizer")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(STYLE)
        self._build_ui()
        self._load_projects()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(272)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 22, 20, 20)
        side.setSpacing(12)
        brand_row = QHBoxLayout()
        logo = QLabel("◉")
        logo.setStyleSheet("color:#6c8bff;font-size:24px")
        brand = QLabel("Ducky Voice")
        brand.setObjectName("Brand")
        brand_row.addWidget(logo)
        brand_row.addWidget(brand)
        brand_row.addStretch()
        side.addLayout(brand_row)
        caption = QLabel("DUAL-MODE LOCAL ONNX")
        caption.setObjectName("Eyebrow")
        side.addWidget(caption)
        side.addSpacing(10)

        self.new_button = QPushButton("＋  New project")
        self.new_button.setObjectName("Primary")
        self.new_button.clicked.connect(self._new_project)
        side.addWidget(self.new_button)
        label = QLabel("PROJECTS")
        label.setObjectName("Eyebrow")
        side.addWidget(label)
        self.project_list = QListWidget()
        self.project_list.currentItemChanged.connect(self._project_selected)
        side.addWidget(self.project_list, 1)
        self.delete_button = QPushButton("Delete project and files")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete_project)
        side.addWidget(self.delete_button)
        local = QLabel("●  Local processing\n    Audio stays on this device")
        local.setObjectName("Subtle")
        local.setStyleSheet("color:#6f8197;font-size:11px")
        side.addWidget(local)
        root.addWidget(sidebar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        main = QVBoxLayout(content)
        main.setContentsMargins(34, 28, 34, 32)
        main.setSpacing(18)

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        self.project_title = QLabel("New voice cleanup")
        self.project_title.setObjectName("Title")
        subtitle = QLabel("Denoise speech, master voice, or split vocals from the background — locally.")
        subtitle.setObjectName("Subtle")
        header_text.addWidget(self.project_title)
        header_text.addWidget(subtitle)
        header.addLayout(header_text)
        header.addStretch()
        self.model_badge = QLabel("●  MODEL READY ON FIRST ENHANCE")
        self.model_badge.setStyleSheet("color:#84d7b1;background:#10251f;border:1px solid #254638;border-radius:10px;padding:8px 12px;font-size:10px;font-weight:700")
        header.addWidget(self.model_badge)
        main.addLayout(header)

        upper = QHBoxLayout()
        upper.setSpacing(16)
        source_card, source_layout = self._card("SOURCE AUDIO", "Bring in a file or capture your microphone")
        self.drop_zone = DropZone()
        self.drop_zone.clicked.connect(self._browse_audio)
        self.drop_zone.file_dropped.connect(self._import_audio)
        source_layout.addWidget(self.drop_zone)
        source_actions = QHBoxLayout()
        self.record_button = QPushButton("●  Record microphone")
        self.record_button.setObjectName("Record")
        self.record_button.setCheckable(True)
        self.record_button.clicked.connect(self._toggle_recording)
        self.remove_audio_button = QPushButton("Remove project audio")
        self.remove_audio_button.setObjectName("Danger")
        self.remove_audio_button.clicked.connect(self._remove_project_audio)
        self.record_time = QLabel("00:00")
        self.record_time.setObjectName("Metric")
        source_actions.addWidget(self.record_button)
        source_actions.addWidget(self.remove_audio_button)
        source_actions.addWidget(self.record_time)
        source_actions.addStretch()
        source_layout.addLayout(source_actions)
        upper.addWidget(source_card, 3)

        settings_card, settings_layout = self._card("VOICE ENHANCEMENT", "Tune cleanup and vocal presence")
        mode_label = QLabel("PROCESSING MODE")
        mode_label.setObjectName("Eyebrow")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.fast_mode = QPushButton("⚡  Fast\nDeepFilterNet3")
        self.quality_mode = QPushButton("✦  High quality\nDPDFNet 48 kHz")
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for button in (self.fast_mode, self.quality_mode):
            button.setObjectName("ModeChoice")
            button.setCheckable(True)
            mode_row.addWidget(button)
            self.mode_group.addButton(button)
        self.fast_mode.setChecked(True)
        self.fast_mode.setToolTip("Lightweight, streaming-friendly enhancement for long recordings and faster CPUs.")
        self.quality_mode.setToolTip("Stronger temporal and cross-band noise suppression; slower and downloads an 11 MB model once.")
        self.mode_hint = QLabel("Fast · lightweight and responsive for everyday recordings")
        self.mode_hint.setObjectName("Subtle")
        self.fast_mode.toggled.connect(self._enhancement_mode_changed)
        settings_layout.addWidget(mode_label)
        settings_layout.addLayout(mode_row)
        settings_layout.addWidget(self.mode_hint)
        self.strength = LabeledSlider("Noise reduction", 0, 100, 100, "%")
        self.clarity = LabeledSlider("Voice clarity", 0, 100, 35, "%")
        self.compression = LabeledSlider("Voice compression", 0, 100, 35, "%")
        self.gain = LabeledSlider("Output gain", -12, 12, 0, " dB")
        self.high_pass = QCheckBox("Voice high-pass filter (80 Hz)")
        self.high_pass.setChecked(True)
        self.normalize = QCheckBox("Normalize output to −1 dB peak")
        self.normalize.setChecked(True)
        self.trim = QCheckBox("Trim leading and trailing silence")
        settings_layout.addWidget(self.strength)
        settings_layout.addWidget(self.clarity)
        settings_layout.addWidget(self.compression)
        settings_layout.addWidget(self.gain)
        settings_layout.addWidget(self.high_pass)
        settings_layout.addWidget(self.normalize)
        settings_layout.addWidget(self.trim)
        upper.addWidget(settings_card, 2)
        main.addLayout(upper)

        editor_card, editor = self._card("PREVIEW", "Compare your source and cleaned result")
        self.waveform = Waveform()
        editor.addWidget(self.waveform)
        transport = QHBoxLayout()
        self.play_button = QPushButton("▶  Play source")
        self.play_button.clicked.connect(lambda: self._play("source"))
        self.result_button = QPushButton("▶  Play cleaned")
        self.result_button.clicked.connect(lambda: self._play("output"))
        self.result_button.setEnabled(False)
        self.vocal_button = QPushButton("▶  Vocals")
        self.vocal_button.clicked.connect(lambda: self._play("vocal"))
        self.vocal_button.setEnabled(False)
        self.background_button = QPushButton("▶  Background")
        self.background_button.clicked.connect(lambda: self._play("background"))
        self.background_button.setEnabled(False)
        self.enhanced_vocal_button = QPushButton("▶  Enhanced vocal")
        self.enhanced_vocal_button.clicked.connect(lambda: self._play("enhanced_vocal"))
        self.enhanced_vocal_button.setEnabled(False)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("Metric")
        transport.addWidget(self.play_button)
        transport.addWidget(self.result_button)
        transport.addWidget(self.vocal_button)
        transport.addWidget(self.background_button)
        transport.addWidget(self.enhanced_vocal_button)
        transport.addStretch()
        transport.addWidget(self.time_label)
        editor.addLayout(transport)
        result_actions = QHBoxLayout()
        self.file_label = QLabel("No audio selected")
        self.file_label.setObjectName("Subtle")
        result_actions.addWidget(self.file_label)
        result_actions.addStretch()
        self.export_button = QPushButton("Export cleaned")
        self.export_button.clicked.connect(self._export_output)
        self.export_button.setEnabled(False)
        self.export_stems_button = QPushButton("Export both stems")
        self.export_stems_button.clicked.connect(self._export_stems)
        self.export_stems_button.setEnabled(False)
        self.export_vocal_button = QPushButton("Download vocal only")
        self.export_vocal_button.clicked.connect(self._export_vocal)
        self.export_vocal_button.setEnabled(False)
        self.enhance_vocal_button = QPushButton("Enhance isolated vocal")
        self.enhance_vocal_button.clicked.connect(self._enhance_vocal)
        self.enhance_vocal_button.setEnabled(False)
        self.delete_vocal_button = QPushButton("Delete vocal")
        self.delete_vocal_button.setObjectName("Danger")
        self.delete_vocal_button.clicked.connect(self._delete_vocal)
        self.delete_vocal_button.setEnabled(False)
        result_actions.addWidget(self.export_button)
        result_actions.addWidget(self.export_vocal_button)
        result_actions.addWidget(self.export_stems_button)
        result_actions.addWidget(self.enhance_vocal_button)
        result_actions.addWidget(self.delete_vocal_button)
        editor.addLayout(result_actions)
        main.addWidget(editor_card, 1)

        footer = QHBoxLayout()
        progress_box = QVBoxLayout()
        self.status_label = QLabel("Ready when you are")
        self.status_label.setObjectName("Metric")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(280)
        progress_box.addWidget(self.status_label)
        progress_box.addWidget(self.progress)
        footer.addLayout(progress_box)
        footer.addStretch()
        self.separate_button = QPushButton("Split vocals + background")
        self.separate_button.clicked.connect(self._separate)
        self.separate_button.setEnabled(False)
        self.enhance_button = QPushButton("✦  Enhance voice")
        self.enhance_button.setObjectName("Primary")
        self.enhance_button.clicked.connect(self._enhance)
        self.enhance_button.setEnabled(False)
        footer.addWidget(self.separate_button)
        footer.addWidget(self.enhance_button)
        main.addLayout(footer)
        root.addWidget(scroll, 1)

    @staticmethod
    def _card(title: str, subtitle: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(11)
        label = QLabel(title)
        label.setObjectName("Eyebrow")
        hint = QLabel(subtitle)
        hint.setObjectName("Subtle")
        layout.addWidget(label)
        layout.addWidget(hint)
        return card, layout

    def _load_projects(self, select_id: int | None = None) -> None:
        self.project_list.blockSignals(True)
        self.project_list.clear()
        selected_row = 0
        projects = self.database.list_projects()
        if not projects:
            projects = [self.database.create_project("My first cleanup")]
        for row, project in enumerate(projects):
            item = QListWidgetItem(f"◌  {project.name}")
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            item.setToolTip(project.name)
            self.project_list.addItem(item)
            if project.id == select_id:
                selected_row = row
        self.project_list.blockSignals(False)
        self.project_list.setCurrentRow(selected_row)
        self._project_selected(self.project_list.currentItem(), None)

    def _new_project(self) -> None:
        project = self.database.create_project(f"Voice cleanup {len(self.database.list_projects()) + 1}")
        self._load_projects(project.id)

    def _project_selected(self, current: QListWidgetItem | None, previous) -> None:
        del previous
        if current is None:
            return
        project_id = int(current.data(Qt.ItemDataRole.UserRole))
        self.current_project = next((p for p in self.database.list_projects() if p.id == project_id), None)
        if self.current_project is None:
            return
        self.player.stop()
        self.project_title.setText(self.current_project.name)
        try:
            settings = json.loads(self.current_project.settings or "{}")
        except json.JSONDecodeError:
            settings = {}
        self.strength.set_value(int(settings.get("strength", 100)))
        self.clarity.set_value(int(settings.get("clarity", 35)))
        self.compression.set_value(int(settings.get("compression", 35)))
        self.gain.set_value(int(settings.get("gain_db", 0)))
        self.high_pass.setChecked(bool(settings.get("high_pass", True)))
        self.normalize.setChecked(bool(settings.get("normalize", True)))
        self.trim.setChecked(bool(settings.get("trim", False)))
        if settings.get("enhancement_mode", "fast") == "quality":
            self.quality_mode.setChecked(True)
        else:
            self.fast_mode.setChecked(True)
        self._enhancement_mode_changed()
        source = self._existing(self.current_project.source_path)
        output = self._existing(self.current_project.output_path)
        vocal = self._existing(self.current_project.vocal_path)
        background = self._existing(self.current_project.background_path)
        enhanced_vocal = self._existing(self.current_project.enhanced_vocal_path)
        self.waveform.set_audio(str(source) if source else None)
        self.file_label.setText(source.name if source else "No audio selected")
        self.enhance_button.setEnabled(source is not None)
        self.separate_button.setEnabled(source is not None)
        self.result_button.setEnabled(output is not None)
        self.vocal_button.setEnabled(vocal is not None)
        self.background_button.setEnabled(background is not None)
        self.enhanced_vocal_button.setEnabled(enhanced_vocal is not None)
        self.export_button.setEnabled(output is not None)
        self.export_stems_button.setEnabled(vocal is not None and background is not None)
        self.export_vocal_button.setEnabled(vocal is not None or enhanced_vocal is not None)
        self.enhance_vocal_button.setEnabled(vocal is not None)
        self.delete_vocal_button.setEnabled(vocal is not None or enhanced_vocal is not None)
        self.remove_audio_button.setEnabled(source is not None or output is not None or vocal is not None)
        self.play_button.setEnabled(source is not None)
        if source:
            duration, sample_rate = audio_info(source)
            self.status_label.setText(f"Source ready · {format_time(duration)} · {sample_rate / 1000:g} kHz")
        else:
            self.status_label.setText("Ready when you are")
        self.progress.setValue(0)

    @staticmethod
    def _existing(path: str | None) -> Path | None:
        candidate = Path(path) if path else None
        return candidate if candidate and candidate.exists() else None

    def _delete_project(self) -> None:
        if not self.current_project:
            return
        answer = QMessageBox.warning(
            self,
            "Delete project?",
            f'Permanently delete “{self.current_project.name}” and all of its audio files?\n\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            folder = (self.projects_root / str(self.current_project.id)).resolve()
            try:
                if folder.parent == self.projects_root.resolve() and folder.exists():
                    shutil.rmtree(folder)
            except OSError as exc:
                self._error(f"The project files could not be removed.\n\n{exc}")
                return
            self.database.delete_project(self.current_project.id)
            self.current_project = None
            self._load_projects()

    def _browse_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose voice recording",
            "",
            "Audio files (*.wav *.flac *.ogg *.aiff *.aif *.mp3);;All files (*)",
        )
        if path:
            self._import_audio(path)

    def _import_audio(self, path: str) -> None:
        if self.worker_thread and self.worker_thread.isRunning():
            return
        if not self.current_project:
            return
        source = Path(path)
        if not source.is_file():
            self._error("That audio file could not be found.")
            return
        try:
            audio_info(source)
        except Exception as exc:
            self._error(f"This audio file could not be opened.\n\n{exc}")
            return
        folder = self.projects_root / str(self.current_project.id)
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"source{source.suffix.lower()}"
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        new_name = source.stem.replace("_", " ").replace("-", " ").strip().title() or self.current_project.name
        self.database.update_project(
            self.current_project.id,
            name=new_name,
            source_path=str(destination.resolve()),
            output_path=None,
            vocal_path=None,
            background_path=None,
            enhanced_vocal_path=None,
        )
        self._load_projects(self.current_project.id)

    def _toggle_recording(self, checked: bool) -> None:
        if self.worker_thread and self.worker_thread.isRunning():
            self.record_button.setChecked(False)
            return
        if not self.current_project:
            return
        if checked:
            try:
                self.recorder.start()
            except Exception as exc:
                self.record_button.setChecked(False)
                self._error(f"Could not start the microphone.\n\n{exc}")
                return
            self.record_started_at = time.monotonic()
            self.record_button.setText("■  Stop recording")
            self.status_label.setText("Recording microphone…")
            self.delete_button.setEnabled(False)
            self.remove_audio_button.setEnabled(False)
            self.new_button.setEnabled(False)
            self.project_list.setEnabled(False)
            self.drop_zone.setEnabled(False)
            self.record_timer.start()
        else:
            self.record_timer.stop()
            destination = self.projects_root / str(self.current_project.id) / "recording.wav"
            try:
                duration = self.recorder.stop(destination)
            except Exception as exc:
                self._error(f"Could not save the recording.\n\n{exc}")
                return
            self.record_button.setText("●  Record microphone")
            self.delete_button.setEnabled(True)
            self.remove_audio_button.setEnabled(True)
            self.new_button.setEnabled(True)
            self.project_list.setEnabled(True)
            self.drop_zone.setEnabled(True)
            if duration < 0.25:
                self._error("The recording was too short. Please record at least one second.")
                return
            self.database.update_project(
                self.current_project.id,
                name=f"Mic recording {time.strftime('%H:%M')}",
                source_path=str(destination.resolve()),
                output_path=None,
                vocal_path=None,
                background_path=None,
                enhanced_vocal_path=None,
            )
            self._load_projects(self.current_project.id)

    def _update_record_time(self) -> None:
        self.record_time.setText(format_time(time.monotonic() - self.record_started_at))

    def _settings(self) -> dict:
        return {
            "enhancement_mode": "quality" if self.quality_mode.isChecked() else "fast",
            "strength": self.strength.value(),
            "clarity": self.clarity.value(),
            "compression": self.compression.value(),
            "gain_db": self.gain.value(),
            "high_pass": self.high_pass.isChecked(),
            "high_pass_hz": 80,
            "normalize": self.normalize.isChecked(),
            "trim": self.trim.isChecked(),
            "threads": 2,
            "attenuation_limit_db": 18.0,
        }

    def _enhancement_mode_changed(self, checked: bool = True) -> None:
        del checked
        if self.quality_mode.isChecked():
            self.mode_hint.setText("High quality · stronger cleanup · 11 MB model downloads once")
            self.model_badge.setText("●  DPDFNET 48 KHZ · LOCAL")
        else:
            self.mode_hint.setText("Fast · lightweight and responsive for everyday recordings")
            self.model_badge.setText("●  DEEPFILTERNET3 · LOCAL")

    def _remove_project_audio(self) -> None:
        if not self.current_project:
            return
        answer = QMessageBox.warning(
            self,
            "Remove all audio?",
            "Permanently remove the imported/recorded audio and every generated result from this project?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        folder = (self.projects_root / str(self.current_project.id)).resolve()
        if folder.parent != self.projects_root.resolve():
            self._error("The project audio folder is invalid; nothing was removed.")
            return
        try:
            if folder.exists():
                shutil.rmtree(folder)
        except OSError as exc:
            self._error(f"The project audio could not be removed.\n\n{exc}")
            return
        self.database.update_project(
            self.current_project.id,
            source_path=None,
            output_path=None,
            vocal_path=None,
            background_path=None,
            enhanced_vocal_path=None,
        )
        self._load_projects(self.current_project.id)

    def _delete_vocal(self) -> None:
        if not self.current_project:
            return
        answer = QMessageBox.warning(
            self,
            "Delete vocal stem?",
            "Permanently delete the isolated and enhanced vocal files? The source and background will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        project_folder = (self.projects_root / str(self.current_project.id)).resolve()
        try:
            for stored_path in (self.current_project.vocal_path, self.current_project.enhanced_vocal_path):
                candidate = Path(stored_path).resolve() if stored_path else None
                if candidate and candidate.parent == project_folder and candidate.exists():
                    candidate.unlink()
        except OSError as exc:
            self._error(f"The vocal file could not be removed.\n\n{exc}")
            return
        self.database.update_project(
            self.current_project.id,
            vocal_path=None,
            enhanced_vocal_path=None,
        )
        self._load_projects(self.current_project.id)

    def _enhance(self) -> None:
        if not self.current_project:
            return
        source = self._existing(self.current_project.source_path)
        if not source:
            self._error("Import or record audio first.")
            return
        settings = self._settings()
        destination = self.projects_root / str(self.current_project.id) / "cleaned.wav"
        self.enhance_target = "output"
        self.database.update_project(self.current_project.id, settings=json.dumps(settings))
        mode_name = "DPDFNet 48 kHz" if settings["enhancement_mode"] == "quality" else "DeepFilterNet3"
        self._start_enhancement_worker(source, destination, settings, f"Preparing {mode_name} ONNX model…")

    def _enhance_vocal(self) -> None:
        if not self.current_project:
            return
        vocal = self._existing(self.current_project.vocal_path)
        if not vocal:
            self._error("Separate vocals first, then enhance the isolated vocal.")
            return
        settings = self._settings()
        destination = self.projects_root / str(self.current_project.id) / "vocals_enhanced.wav"
        self.enhance_target = "enhanced_vocal"
        self.database.update_project(self.current_project.id, settings=json.dumps(settings))
        mode_name = "DPDFNet 48 kHz" if settings["enhancement_mode"] == "quality" else "DeepFilterNet3"
        self._start_enhancement_worker(vocal, destination, settings, f"Enhancing isolated vocal with {mode_name}…")

    def _start_enhancement_worker(self, source: Path, destination: Path, settings: dict, status: str) -> None:
        self.enhance_button.setEnabled(False)
        self.enhance_vocal_button.setEnabled(False)
        self.delete_vocal_button.setEnabled(False)
        self.separate_button.setEnabled(False)
        self.new_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.record_button.setEnabled(False)
        self.remove_audio_button.setEnabled(False)
        self.drop_zone.setEnabled(False)
        self.project_list.setEnabled(False)
        self.fast_mode.setEnabled(False)
        self.quality_mode.setEnabled(False)
        self.progress.setValue(2)
        self.status_label.setText(status)
        self.model_badge.setText("●  PROCESSING LOCALLY")
        self.active_enhancement_mode = settings.get("enhancement_mode", "fast")
        self.worker_thread = QThread(self)
        self.worker = EnhanceWorker(source, destination, settings, self.models_root)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._enhance_progress)
        self.worker.finished.connect(self._enhance_finished)
        self.worker.failed.connect(self._enhance_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _separate(self) -> None:
        if not self.current_project:
            return
        source = self._existing(self.current_project.source_path)
        if not source:
            self._error("Import or record audio first.")
            return
        folder = self.projects_root / str(self.current_project.id)
        vocals = folder / "vocals.wav"
        background = folder / "background.wav"
        self.enhance_button.setEnabled(False)
        self.separate_button.setEnabled(False)
        self.new_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.record_button.setEnabled(False)
        self.remove_audio_button.setEnabled(False)
        self.enhance_vocal_button.setEnabled(False)
        self.delete_vocal_button.setEnabled(False)
        self.drop_zone.setEnabled(False)
        self.project_list.setEnabled(False)
        self.progress.setValue(2)
        self.status_label.setText("Preparing UVR MDX-Net vocal model…")
        self.model_badge.setText("●  SEPARATING LOCALLY")

        self.worker_thread = QThread(self)
        self.worker = SeparateWorker(source, vocals, background, self.models_root)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._separate_progress)
        self.worker.finished.connect(self._separate_finished)
        self.worker.failed.connect(self._separate_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _separate_progress(self, value: int) -> None:
        self.progress.setValue(value)
        if value < 42:
            self.status_label.setText(f"Downloading vocal model… {value}%")
        elif value < 56:
            self.status_label.setText("Loading UVR MDX-Net ONNX model…")
        elif value < 100:
            self.status_label.setText("Separating vocals from background…")

    def _separate_finished(self, vocal_path: str, background_path: str) -> None:
        if self.current_project:
            self.database.update_project(
                self.current_project.id,
                vocal_path=str(Path(vocal_path).resolve()),
                background_path=str(Path(background_path).resolve()),
            )
            latest = next((p for p in self.database.list_projects() if p.id == self.current_project.id), None)
            if latest:
                self.current_project = latest
        self.progress.setValue(100)
        self.status_label.setText("Separation complete · vocals and background ready")
        self._enhancement_mode_changed()
        self._set_busy_finished()
        self.vocal_button.setEnabled(True)
        self.background_button.setEnabled(True)
        self.export_stems_button.setEnabled(True)
        self.export_vocal_button.setEnabled(True)
        self.enhance_vocal_button.setEnabled(True)
        self.delete_vocal_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None

    def _separate_failed(self, message: str) -> None:
        self.progress.setValue(0)
        self.status_label.setText("Vocal separation failed")
        self.model_badge.setText("●  MODEL NEEDS ATTENTION")
        self._set_busy_finished()
        self._error(f"Vocal separation failed.\n\n{message}")
        self.worker = None
        self.worker_thread = None

    def _enhance_progress(self, value: int) -> None:
        self.progress.setValue(value)
        if self.active_enhancement_mode == "quality" and value < 42:
            self.status_label.setText(f"Downloading high-quality model… {value}%")
        elif self.active_enhancement_mode == "quality" and value < 53:
            self.status_label.setText("Loading DPDFNet 48 kHz ONNX model…")
        elif value >= 10:
            self.status_label.setText(f"Removing noise… {value}%")

    def _enhance_finished(self, path: str) -> None:
        if self.current_project:
            field = "enhanced_vocal_path" if self.enhance_target == "enhanced_vocal" else "output_path"
            self.database.update_project(self.current_project.id, **{field: str(Path(path).resolve())})
            latest = next((p for p in self.database.list_projects() if p.id == self.current_project.id), None)
            if latest:
                self.current_project = latest
        self.progress.setValue(100)
        is_vocal = self.enhance_target == "enhanced_vocal"
        self.status_label.setText("Isolated vocal enhancement complete" if is_vocal else "Voice enhancement complete")
        self._enhancement_mode_changed()
        self._set_busy_finished()
        if is_vocal:
            self.enhanced_vocal_button.setEnabled(True)
            self.export_vocal_button.setEnabled(True)
        else:
            self.result_button.setEnabled(True)
            self.export_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None

    def _enhance_failed(self, message: str) -> None:
        self.progress.setValue(0)
        self.status_label.setText("Enhancement failed")
        self.model_badge.setText("●  MODEL NEEDS ATTENTION")
        self._set_busy_finished()
        self._error(f"Voice enhancement failed.\n\n{message}")
        self.worker = None
        self.worker_thread = None

    def _set_busy_finished(self) -> None:
        self.enhance_button.setEnabled(True)
        self.separate_button.setEnabled(True)
        self.new_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.record_button.setEnabled(True)
        self.remove_audio_button.setEnabled(True)
        self.enhance_vocal_button.setEnabled(
            bool(self.current_project and self._existing(self.current_project.vocal_path))
        )
        self.delete_vocal_button.setEnabled(
            bool(
                self.current_project
                and (
                    self._existing(self.current_project.vocal_path)
                    or self._existing(self.current_project.enhanced_vocal_path)
                )
            )
        )
        self.drop_zone.setEnabled(True)
        self.project_list.setEnabled(True)
        self.fast_mode.setEnabled(True)
        self.quality_mode.setEnabled(True)

    def _play(self, kind: str) -> None:
        if not self.current_project:
            return
        paths = {
            "source": self.current_project.source_path,
            "output": self.current_project.output_path,
            "vocal": self.current_project.vocal_path,
            "background": self.current_project.background_path,
            "enhanced_vocal": self.current_project.enhanced_vocal_path,
        }
        path = paths[kind]
        # Refresh because output_path may have changed after worker completion.
        if kind != "source":
            latest = next((p for p in self.database.list_projects() if p.id == self.current_project.id), None)
            if latest:
                path = {
                    "output": latest.output_path,
                    "vocal": latest.vocal_path,
                    "background": latest.background_path,
                    "enhanced_vocal": latest.enhanced_vocal_path,
                }[kind]
            if latest:
                self.current_project = latest
        valid = self._existing(path)
        if not valid:
            return
        current = self.player.source().toLocalFile()
        if current == str(valid) and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            return
        if current != str(valid):
            self.player.setSource(QUrl.fromLocalFile(str(valid)))
            self.waveform.set_audio(str(valid))
        self.playing_kind = kind
        self.player.play()

    def _playback_position(self, value: int) -> None:
        duration = self.player.duration()
        self.time_label.setText(f"{format_time(value / 1000)} / {format_time(duration / 1000)}")
        self.waveform.set_progress(value / duration if duration else 0.0)

    def _playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("▶  Play source")
        self.result_button.setText("▶  Play cleaned")
        self.vocal_button.setText("▶  Vocals")
        self.background_button.setText("▶  Background")
        self.enhanced_vocal_button.setText("▶  Enhanced vocal")
        if is_playing:
            button = {
                "source": self.play_button,
                "output": self.result_button,
                "vocal": self.vocal_button,
                "background": self.background_button,
                "enhanced_vocal": self.enhanced_vocal_button,
            }[self.playing_kind]
            button.setText("Ⅱ  Pause")

    def _export_output(self) -> None:
        if not self.current_project:
            return
        latest = next((p for p in self.database.list_projects() if p.id == self.current_project.id), None)
        output = self._existing(latest.output_path if latest else self.current_project.output_path)
        if not output:
            return
        suggested = f"{self.current_project.name.replace(' ', '_')}_cleaned.wav"
        path, _ = QFileDialog.getSaveFileName(self, "Export cleaned audio", suggested, "WAV audio (*.wav)")
        if path:
            if not path.lower().endswith(".wav"):
                path += ".wav"
            shutil.copy2(output, path)
            self.status_label.setText(f"Exported · {Path(path).name}")

    def _export_stems(self) -> None:
        if not self.current_project:
            return
        latest = next((p for p in self.database.list_projects() if p.id == self.current_project.id), None)
        vocals = self._existing(latest.vocal_path if latest else self.current_project.vocal_path)
        background = self._existing(latest.background_path if latest else self.current_project.background_path)
        if not vocals or not background:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose folder for vocal stems")
        if folder:
            safe_name = self.current_project.name.replace(" ", "_")
            shutil.copy2(vocals, Path(folder) / f"{safe_name}_vocals.wav")
            shutil.copy2(background, Path(folder) / f"{safe_name}_background.wav")
            self.status_label.setText("Exported vocal and background stems")

    def _export_vocal(self) -> None:
        if not self.current_project:
            return
        latest = next((p for p in self.database.list_projects() if p.id == self.current_project.id), None)
        project = latest or self.current_project
        enhanced = self._existing(project.enhanced_vocal_path)
        vocal = enhanced or self._existing(project.vocal_path)
        if not vocal:
            return
        suffix = "enhanced_vocal" if enhanced else "vocal"
        suggested = f"{project.name.replace(' ', '_')}_{suffix}.wav"
        path, _ = QFileDialog.getSaveFileName(self, "Download vocal only", suggested, "WAV audio (*.wav)")
        if path:
            if not path.lower().endswith(".wav"):
                path += ".wav"
            shutil.copy2(vocal, path)
            self.status_label.setText(f"Exported vocal · {Path(path).name}")

    def _error(self, message: str) -> None:
        QMessageBox.critical(self, "Ducky Voice Optimizer", message)

    def closeEvent(self, event) -> None:
        if self.recorder.active:
            self.record_timer.stop()
            try:
                self.recorder.stop(self.projects_root / "recovered_recording.wav")
            except Exception:
                pass
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.information(self, "Enhancement running", "Please wait for the current enhancement to finish.")
            event.ignore()
            return
        event.accept()
