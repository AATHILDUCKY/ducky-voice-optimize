from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "assets" / "ducky-voice-optimizer.png"
image = Image.open(source).convert("RGBA")

# Keep one high-resolution Linux icon and build a multi-resolution Windows ICO.
image.resize((512, 512), Image.Resampling.LANCZOS).save(
    ROOT / "assets" / "ducky-voice-optimizer-512.png"
)
image.save(
    ROOT / "assets" / "ducky-voice-optimizer.ico",
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("Application PNG and ICO generated.")

