"""Generate synthetic fixtures. No recordings or third-party audio are used."""
import math
from pathlib import Path
import struct
import wave

root = Path(__file__).resolve().parent / "assets"
root.mkdir(exist_ok=True)
rate = 48000


def write(name, samples):
    with wave.open(str(root / name), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


write("tone_reference.wav", [int(10000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(rate)])
write("silence_check.wav", [0] * rate)
write("rail_hits.wav", [32767, -32768] * (rate // 2))
(root / "duplicate_tone.wav").write_bytes((root / "tone_reference.wav").read_bytes())
(root / "broken_asset.wav").write_bytes(b"deliberately invalid WAV for QA")
print(root)
