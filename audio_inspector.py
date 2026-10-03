"""Inspect integer PCM WAV assets without modifying source audio."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import wave

VERSION = "1.0.0"


def decode_pcm(data: bytes, width: int) -> list[int] | array:
    if len(data) % width:
        raise ValueError("Incomplete PCM sample")
    if width == 1:
        return [value - 128 for value in data]
    if width in (2, 4):
        samples = array("h" if width == 2 else "i")
        samples.frombytes(data)
        if sys.byteorder != "little":
            samples.byteswap()
        return samples
    if width == 3:
        return [int.from_bytes(data[i:i + 3], "little", signed=True)
                for i in range(0, len(data), 3)]
    raise ValueError(f"Unsupported sample width: {width}")


def dbfs(amplitude: float) -> float | None:
    return round(20 * math.log10(amplitude), 2) if amplitude > 0 else None


def inspect_asset(path: Path, root: Path) -> dict:
    relative = path.relative_to(root).as_posix()
    result = {"path": relative, "status": "ok", "issues": []}
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return {**result, "status": "error", "issues": ["Symlink escapes asset root"]}
    try:
        digest = hashlib.sha256()
        with path.open("rb") as raw:
            for chunk in iter(lambda: raw.read(1024 * 1024), b""):
                digest.update(chunk)
        result["sha256"] = digest.hexdigest()
        with wave.open(str(path), "rb") as audio:
            channels, width, rate, declared, compression, _ = audio.getparams()
            if compression != "NONE" or width not in (1, 2, 3, 4):
                raise ValueError("Only uncompressed integer PCM WAV is supported")
            result.update(channels=channels, sample_rate=rate, bit_depth=width * 8,
                          frames=declared, duration_seconds=round(declared / rate, 6))
            count = peak = clipped = frames_read = 0
            squares = 0
            channel_sums = [0] * channels
            full_scale = 1 << (width * 8 - 1)
            while True:
                data = audio.readframes(16384)
                if not data:
                    break
                if len(data) % (channels * width):
                    raise ValueError("Incomplete audio frame")
                samples = decode_pcm(data, width)
                frames_read += len(samples) // channels
                for index, value in enumerate(samples):
                    absolute = abs(value)
                    peak = max(peak, absolute)
                    squares += value * value
                    channel_sums[index % channels] += value
                    # Rail hits flag clipping risk; they do not prove audible distortion.
                    clipped += absolute >= full_scale - 1
                count += len(samples)
            if frames_read != declared:
                raise ValueError(f"Truncated PCM: header declares {declared} frames; read {frames_read}")
            result.update(peak_dbfs=dbfs(peak / full_scale),
                          rms_dbfs=dbfs(math.sqrt(squares / count) / full_scale) if count else None,
                          rail_hit_samples=clipped,
                          dc_offset_by_channel=[round(value / frames_read / full_scale, 6)
                                                if frames_read else 0 for value in channel_sums])
        issues = result["issues"]
        if not declared:
            issues.append("Empty audio asset")
        elif not peak:
            issues.append("Digital silence")
        if clipped:
            issues.append("PCM rail hits: review clipping risk")
        if any(abs(offset) > 0.01 for offset in result["dc_offset_by_channel"]):
            issues.append("DC offset above 1% in at least one channel")
        if rate not in (44100, 48000):
            issues.append("Sample rate outside project defaults (44100/48000 Hz)")
        if channels not in (1, 2):
            issues.append("Channel count outside project defaults (mono/stereo)")
        if width not in (2, 3):
            issues.append("Bit depth outside project defaults (16/24 bit)")
        if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*\.wav", path.name):
            issues.append("Use lowercase snake_case asset names")
        result["status"] = "warning" if issues else "ok"
    except (OSError, EOFError, wave.Error, ValueError, ZeroDivisionError) as error:
        result["status"] = "error"
        result["issues"] = [f"Cannot inspect WAV: {error}"]
    return result


def scan(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("Asset root must be an existing directory")
    paths = sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".wav"),
                   key=lambda p: p.relative_to(root).as_posix())
    assets = [inspect_asset(path, root) for path in paths]
    hashes: dict[str, list[str]] = {}
    for asset in assets:
        if asset["status"] != "error":
            hashes.setdefault(asset["sha256"], []).append(asset["path"])
    duplicates = [group for group in hashes.values() if len(group) > 1]
    return {"schema_version": 1, "tool_version": VERSION,
            "scope": "Integer PCM WAV validation; no Wwise integration or perceptual quality scoring",
            "summary": {"total": len(assets), **{status: sum(a["status"] == status for a in assets)
                        for status in ("ok", "warning", "error")}, "duplicate_groups": len(duplicates)},
            "duplicate_groups": duplicates, "assets": assets}


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".audio-report-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def render_html(report: dict) -> str:
    rows = []
    for asset in report["assets"]:
        cells = [html.escape(str(asset.get(field, "-"))) for field in
                 ("path", "status", "duration_seconds", "sample_rate", "channels", "bit_depth", "peak_dbfs")]
        issues = html.escape("; ".join(asset["issues"]) or "No flagged issues")
        rows.append(f'<tr data-status="{asset["status"]}"><td>' + '</td><td>'.join(cells) + f'</td><td>{issues}</td></tr>')
    summary = report["summary"]
    duplicate_lines = ''.join('<li>' + html.escape(' / '.join(group)) + '</li>'
                              for group in report["duplicate_groups"])
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Audio Pipeline Inspector</title><style>
body{font:16px/1.6 system-ui;background:#f6f7f8;color:#18242b;margin:0;padding:32px}main{max-width:1200px;margin:auto}
h1{font-size:32px;margin-bottom:0}p{max-width:85ch}.stats{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}
.stats span{background:white;border:1px solid #dae0e5;border-radius:8px;padding:12px 18px}select{font:inherit;padding:8px;margin:8px}
.table{overflow:auto;background:white;border:1px solid #dae0e5}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:12px;text-align:left;border-bottom:1px solid #e5e8eb}th{background:#eef2f4}tr[data-status="error"]{background:#fff0ee}
tr[data-status="warning"]{background:#fffbea}a{color:#125f89}footer{margin-top:24px;color:#52616c}
</style><main><h1>Audio Pipeline Inspector</h1><p>Read-only asset checks for an audio delivery workflow. Flags are review prompts, not a guarantee of quality.</p>
<div class="stats">''' + ''.join(f'<span><strong>{summary[key]}</strong> {key}</span>' for key in ('total', 'ok', 'warning', 'error')) + '''</div>
<label for="filter">Show assets</label><select id="filter"><option value="all">All</option><option>ok</option><option>warning</option><option>error</option></select>
<div class="table"><table><thead><tr><th>Asset</th><th>Status</th><th>Seconds</th><th>Hz</th><th>Channels</th><th>Bits</th><th>Peak dBFS</th><th>Review notes</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table></div>
<h2>Identical files</h2><ul>''' + (duplicate_lines or '<li>No identical files detected.</li>') + '''</ul>
<footer>Supports integer PCM WAV. No normalization, audio rewriting, Wwise connection, or inferred perceptual judgments.</footer></main>
<script>document.getElementById('filter').addEventListener('change',function(){document.querySelectorAll('tbody tr').forEach(row=>row.hidden=this.value!=='all'&&row.dataset.status!==this.value);});</script></html>'''


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--html-report", type=Path)
    parser.add_argument("--strict", action="store_true", help="Exit 1 on warnings or duplicates; errors always exit 2")
    args = parser.parse_args(argv)
    try:
        report = scan(args.assets)
        output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.json_report:
            atomic_write(args.json_report, output)
        else:
            print(output, end="")
        if args.html_report:
            atomic_write(args.html_report, render_html(report))
        summary = report["summary"]
        return 2 if summary["error"] else (1 if args.strict and (summary["warning"] or summary["duplicate_groups"]) else 0)
    except (OSError, ValueError) as error:
        print(f"audio-inspector: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
