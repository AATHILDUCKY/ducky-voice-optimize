# Ducky Voice Optimizer

Professional local desktop audio cleanup and vocal-separation software for Windows 10/11 and Ubuntu. The application uses PyQt6, SQLite, DeepFilterNet3 ONNX, DPDFNet ONNX, and UVR MDX-Net ONNX.

## Audio workflow

- Create and permanently delete multiple projects.
- Import WAV, FLAC, OGG, AIFF, or supported MP3 audio by picker or drag-and-drop.
- Record a microphone directly into a project.
- Remove every audio file from a project without deleting its project entry.
- Choose **Fast** DeepFilterNet3 enhancement for responsive processing on modest hardware.
- Choose **High quality** DPDFNet 48 kHz enhancement for stronger temporal and cross-band noise suppression.
- Enhance voice with adjustable noise-reduction blend, high-pass filtering, clarity EQ, compression, output gain, normalization, and silence trimming.
- Separate vocals and background into independent stereo stems with UVR MDX-Net.
- Enhance and denoise the isolated vocal after separation.
- Preview source, cleaned audio, vocal, background, and enhanced vocal independently.
- Download only the vocal, export cleaned audio, or export both stems.
- Delete only vocal files while retaining the source and background.
- Run AI models in background workers so the interface remains responsive.

## Run from source

```bash
chmod +x run.sh
./run.sh
```

The first use of each AI feature requires internet access to obtain its model. Models are cached locally afterward.

## Ubuntu installation

Prebuilt amd64 artifacts are in `release/`:

```bash
sudo dpkg -i release/ducky-voice-optimizer_1.3.0_amd64.deb
sudo apt -f install
```

Alternatively, `sudo apt install ./release/ducky-voice-optimizer_1.3.0_amd64.deb` installs dependencies automatically.

Portable AppImage:

```bash
chmod +x release/ducky-voice-optimizer-1.3.0-x86_64.AppImage
./release/ducky-voice-optimizer-1.3.0-x86_64.AppImage
```

### Build Ubuntu packages

```bash
sudo apt install python3-venv dpkg-dev curl libportaudio2 libsndfile1 ffmpeg
./build.sh
```

`build.sh` creates both formats under `release/`. Native targets:

- `x86_64` → Debian `amd64` and AppImage `x86_64`
- `aarch64` → Debian `arm64` and AppImage `aarch64`

Build arm64 packages on an arm64 Ubuntu host. Native AI-library wheels must be available for the selected Python version.

## Windows 10 and Windows 11

The Windows package uses PyInstaller and Inno Setup. It provides a standard wizard with license acceptance, destination selection, an optional desktop shortcut, installation progress, launch, and uninstall support.

Install 64-bit Python 3.10+ matching the target architecture and Inno Setup 6 or 7. Then double-click `build-windows.bat`, or run:

```powershell
.\build-windows.ps1 -Architecture x64
# On native Windows Arm64 with Arm64 Python:
.\build-windows.ps1 -Architecture arm64
```

The installer appears under `release/`. Windows binaries must be built on Windows because PyInstaller is not a cross-compiler. The installer requires Windows 10 or 11 and validates x64/Arm64 compatibility.

For public distribution, digitally sign the EXE and installer with an Authenticode certificate to avoid Microsoft SmartScreen “unknown publisher” warnings.

## Application data

Writable projects are never stored beside the installed executable.

- Windows: `%LOCALAPPDATA%\Ducky Voice Optimizer\ducky-voice-optimizer\`
- Ubuntu: `~/.local/share/Ducky Voice Optimizer/ducky-voice-optimizer/`

This folder contains `projects.sqlite3`, project audio, and cached separation models. Project and audio deletion are permanent and protected by confirmation dialogs.

## Models

- DeepFilterNet3 performs full-band speech denoising at 48 kHz internally.
- DPDFNet2 HR is the optional quality-focused mode. It uses stronger long-range temporal and cross-band modeling, runs locally through sherpa-onnx, and downloads an approximately 11 MB verified model on first use.
- `UVR-MDX-NET-Voc_FT.onnx` separates vocal/non-vocal stems. It is downloaded from the official sherpa-onnx release and SHA-256 verified before caching.

To use a compatible local DeepFilterNet3 bundle:

```bash
export DEEPFILTER_STREAM_MODEL_DIR=/path/to/dfn3-512-v1
./run.sh
```

The folder must contain `denoiser_model.onnx`, `initial_states.npz`, and `meta.json`.

## Terms and attribution

The Windows installer displays [TERMS.txt](TERMS.txt). Users must have rights to process and distribute imported audio.

- DeepFilterNet3: Hendrik Schröter and contributors, MIT or Apache-2.0.
- DPDFNet: Ceva-IP; the ONNX model is distributed through the official sherpa-onnx speech-enhancement release and retains its model-specific terms.
- sherpa-onnx: k2-fsa, Apache-2.0.
- UVR MDX-Net model: distributed through sherpa-onnx; model-specific terms continue to apply.
- PyQt6/Qt and packaged dependencies retain their respective licenses.
