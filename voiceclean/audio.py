from __future__ import annotations

import hashlib
import os
import threading
import urllib.request
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import butter, resample_poly, sosfilt


UVR_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "source-separation-models/UVR-MDX-NET-Voc_FT.onnx"
)
UVR_MODEL_NAME = "UVR-MDX-NET-Voc_FT.onnx"
UVR_MODEL_SHA256 = "e411182ce2c53541fefdcc99a8f46f2fe03978eb22038b9497c1d9d95a00fad4"
DPDFNET_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speech-enhancement-models/dpdfnet2_48khz_hr.onnx"
)
DPDFNET_MODEL_NAME = "dpdfnet2_48khz_hr.onnx"
DPDFNET_MODEL_SHA256 = "0b399f8a58dc4d70d8cd97541f5c39869406145193b957d00a03b66070944928"


def load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(path, always_2d=False, dtype="float32")
    if audio.ndim == 2:
        audio = np.mean(audio, axis=1, dtype=np.float32)
    if audio.size == 0:
        raise ValueError("The selected audio file is empty.")
    return np.ascontiguousarray(audio, dtype=np.float32), sample_rate


def load_audio_multichannel(path: str | Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(path, always_2d=True, dtype="float32")
    if audio.size == 0:
        raise ValueError("The selected audio file is empty.")
    # sherpa-onnx uses channel-first contiguous float32 audio.
    return np.ascontiguousarray(audio.T, dtype=np.float32), sample_rate


def audio_info(path: str | Path) -> tuple[float, int]:
    info = sf.info(path)
    return float(info.duration), int(info.samplerate)


def waveform_peaks(path: str | Path, points: int = 900) -> np.ndarray:
    audio, _ = load_audio(path)
    if len(audio) <= points:
        return audio
    usable = len(audio) - (len(audio) % points)
    blocks = audio[:usable].reshape(points, -1)
    return np.max(np.abs(blocks), axis=1).astype(np.float32)


def _trim_silence(audio: np.ndarray, threshold_db: float = -52.0) -> np.ndarray:
    threshold = 10 ** (threshold_db / 20)
    indices = np.flatnonzero(np.abs(audio) > threshold)
    if indices.size == 0:
        return audio
    pad = min(2400, len(audio) // 20)
    start = max(0, int(indices[0]) - pad)
    end = min(len(audio), int(indices[-1]) + pad + 1)
    return audio[start:end]


def _voice_master(audio: np.ndarray, sample_rate: int, clarity: float, compression: float) -> np.ndarray:
    """Apply conservative presence EQ and smooth speech compression."""
    if clarity > 0 and len(audio) > 24:
        # Parallel high-frequency emphasis is a stable, phase-coherent presence control.
        sos = butter(2, 2600, btype="highpass", fs=sample_rate, output="sos")
        presence = sosfilt(sos, audio).astype(np.float32)
        audio = audio + presence * (0.32 * clarity)

    if compression > 0 and len(audio) > 24:
        look = max(3, int(sample_rate * 0.008))
        release = max(3, int(sample_rate * 0.060))
        envelope = maximum_filter1d(np.abs(audio), size=look, mode="nearest")
        envelope = uniform_filter1d(envelope, size=release, mode="nearest")
        threshold = 10 ** (-18.0 / 20.0)
        ratio = 1.0 + 3.0 * compression
        over = np.maximum(envelope / threshold, 1.0)
        gain = np.power(over, -(1.0 - 1.0 / ratio))
        # Parallel blend makes the amount control musical and avoids abrupt pumping.
        audio = audio * ((1.0 - compression) + compression * gain)
        makeup = 10 ** ((4.5 * compression) / 20.0)
        audio *= makeup
    return audio.astype(np.float32)


def enhance_file(
    source: Path,
    destination: Path,
    settings: dict,
    model_dir: Path,
    progress: Callable[[int], None] | None = None,
) -> None:
    """Enhance one file with the selected local ONNX speech model."""
    mode = settings.get("enhancement_mode", "fast")
    audio, sample_rate = load_audio(source)
    original = audio.copy()

    if settings.get("high_pass", True) and len(audio) > 24:
        cutoff = min(float(settings.get("high_pass_hz", 80)), sample_rate * 0.45)
        sos = butter(2, cutoff, btype="highpass", fs=sample_rate, output="sos")
        audio = sosfilt(sos, audio).astype(np.float32)

    if mode == "quality":
        wet = _enhance_dpdfnet(audio, sample_rate, model_dir, settings, progress)
    else:
        wet = _enhance_deepfilter(audio, sample_rate, settings, progress)

    # Keep model delay/tail behavior bounded to source length for predictable editing.
    if len(wet) < len(original):
        wet = np.pad(wet, (0, len(original) - len(wet)))
    wet = wet[: len(original)]
    strength = float(settings.get("strength", 100)) / 100.0
    output = wet * strength + original * (1.0 - strength)

    output = _voice_master(
        output,
        sample_rate,
        float(settings.get("clarity", 35)) / 100.0,
        float(settings.get("compression", 35)) / 100.0,
    )

    gain = 10 ** (float(settings.get("gain_db", 0.0)) / 20.0)
    output *= gain
    if settings.get("trim", False):
        output = _trim_silence(output)
    if settings.get("normalize", True):
        peak = float(np.max(np.abs(output))) if output.size else 0.0
        if peak > 1e-7:
            target = 10 ** (-1.0 / 20.0)
            output *= target / peak
    output = np.clip(output, -1.0, 1.0).astype(np.float32)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(destination, output, sample_rate, subtype="PCM_16")
    if progress:
        progress(100)


def _enhance_deepfilter(
    audio: np.ndarray,
    sample_rate: int,
    settings: dict,
    progress: Callable[[int], None] | None,
) -> np.ndarray:
    """Fast, streaming-friendly DeepFilterNet3 enhancement."""
    try:
        from deepfilter_stream import DeepFilterModel
    except ImportError as exc:
        raise RuntimeError("deepfilter-stream is not installed. Run ./run.sh again.") from exc

    if progress:
        progress(8)
    model = DeepFilterModel(intra_op_num_threads=max(1, int(settings.get("threads", 2))))
    stream = model.new_stream(atten_lim_db=None)

    # Chunking gives responsive progress while retaining recurrent model state.
    block = max(sample_rate * 2, 4096)
    chunks: list[np.ndarray] = []
    total = len(audio)
    for start in range(0, total, block):
        piece = stream.process(audio[start : start + block], sr=sample_rate)
        chunks.append(np.asarray(piece, dtype=np.float32))
        if progress:
            progress(10 + int(75 * min(total, start + block) / total))
    tail = stream.flush()
    if tail is not None and len(tail):
        chunks.append(np.asarray(tail, dtype=np.float32))
    return np.concatenate(chunks) if chunks else audio


def _enhance_dpdfnet(
    audio: np.ndarray,
    sample_rate: int,
    model_dir: Path,
    settings: dict,
    progress: Callable[[int], None] | None,
) -> np.ndarray:
    """Quality-focused 48 kHz DPDFNet enhancement using sherpa-onnx."""
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise RuntimeError("sherpa-onnx is not installed. Run ./run.sh again.") from exc

    model_path = model_dir / DPDFNET_MODEL_NAME
    if not model_path.exists():
        _download_verified_model(
            DPDFNET_MODEL_URL,
            model_path,
            DPDFNET_MODEL_SHA256,
            "high-quality enhancement",
            progress,
            4,
            36,
        )
    if progress:
        progress(42)
    config = sherpa_onnx.OfflineSpeechDenoiserConfig(
        model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
            dpdfnet=sherpa_onnx.OfflineSpeechDenoiserDpdfNetModelConfig(
                model=str(model_path),
                # Retain a small amount of the input to reduce speech over-suppression.
                attenuation_limit_db=float(settings.get("attenuation_limit_db", 18.0)),
            ),
            debug=False,
            num_threads=max(1, int(settings.get("threads", 2))),
            provider="cpu",
        )
    )
    if not config.validate():
        raise RuntimeError("The DPDFNet enhancement model configuration is invalid.")
    denoiser = sherpa_onnx.OfflineSpeechDenoiser(config)
    if progress:
        progress(52)
    denoised = denoiser(np.ascontiguousarray(audio, dtype=np.float32), sample_rate)
    wet = np.asarray(denoised.samples, dtype=np.float32)
    output_rate = int(denoised.sample_rate)
    if progress:
        progress(86)
    if output_rate != sample_rate and wet.size:
        divisor = int(np.gcd(output_rate, sample_rate))
        wet = resample_poly(wet, sample_rate // divisor, output_rate // divisor).astype(np.float32)
    return wet


def _download_verified_model(
    url: str,
    model_path: Path,
    expected_sha256: str,
    label: str,
    progress: Callable[[int], None] | None,
    progress_start: int,
    progress_end: int,
) -> None:
    """Atomically download and verify an ONNX model before making it available."""
    model_path.parent.mkdir(parents=True, exist_ok=True)
    partial = model_path.with_suffix(model_path.suffix + ".download")
    request = urllib.request.Request(url, headers={"User-Agent": "Ducky-Voice-Optimizer/1.3"})
    try:
        hasher = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as target:
            total = int(response.headers.get("Content-Length", 0))
            received = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                hasher.update(chunk)
                received += len(chunk)
                if progress and total:
                    span = progress_end - progress_start
                    progress(progress_start + int(span * received / total))
        if hasher.hexdigest() != expected_sha256:
            raise RuntimeError(f"The {label} model failed its integrity check.")
        os.replace(partial, model_path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _download_model(model_path: Path, progress: Callable[[int], None] | None) -> None:
    _download_verified_model(
        UVR_MODEL_URL,
        model_path,
        UVR_MODEL_SHA256,
        "vocal-separation",
        progress,
        5,
        40,
    )


def separate_vocals(
    source: Path,
    vocals_path: Path,
    background_path: Path,
    model_dir: Path,
    progress: Callable[[int], None] | None = None,
) -> None:
    """Separate a track into vocal and non-vocal stems using UVR MDX-Net ONNX."""
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise RuntimeError("sherpa-onnx is not installed. Run ./run.sh again.") from exc

    model_path = model_dir / UVR_MODEL_NAME
    if not model_path.exists():
        if progress:
            progress(4)
        _download_model(model_path, progress)
    if progress:
        progress(44)

    config = sherpa_onnx.OfflineSourceSeparationConfig(
        model=sherpa_onnx.OfflineSourceSeparationModelConfig(
            uvr=sherpa_onnx.OfflineSourceSeparationUvrModelConfig(model=str(model_path)),
            num_threads=2,
            debug=False,
            provider="cpu",
        )
    )
    if not config.validate():
        raise RuntimeError("The UVR vocal-separation model configuration is invalid.")
    separator = sherpa_onnx.OfflineSourceSeparation(config)
    samples, sample_rate = load_audio_multichannel(source)
    if progress:
        progress(55)
    output = separator.process(sample_rate=sample_rate, samples=samples)
    if len(output.stems) != 2:
        raise RuntimeError(f"The separation model returned {len(output.stems)} stems instead of 2.")
    vocals = np.asarray(output.stems[0].data, dtype=np.float32).T
    background = np.asarray(output.stems[1].data, dtype=np.float32).T
    vocals_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(vocals_path, np.clip(vocals, -1, 1), output.sample_rate, subtype="PCM_16")
    sf.write(background_path, np.clip(background, -1, 1), output.sample_rate, subtype="PCM_16")
    if progress:
        progress(100)


class Recorder:
    def __init__(self) -> None:
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self.sample_rate = 48000

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd

        self._chunks.clear()

        def callback(indata, frames, time_info, status):
            del frames, time_info, status
            with self._lock:
                self._chunks.append(indata[:, 0].copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=960,
            callback=callback,
        )
        self._stream.start()

    def stop(self, destination: Path) -> float:
        if self._stream is None:
            return 0.0
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(1, dtype=np.float32)
            self._chunks.clear()
        destination.parent.mkdir(parents=True, exist_ok=True)
        sf.write(destination, audio, self.sample_rate, subtype="PCM_16")
        return len(audio) / self.sample_rate
