# Audio Pipeline Inspector

A small Python tool for inspecting integer PCM WAV assets before audio delivery.

A portfolio project exploring practical audio-delivery checks with Python. All demo audio is generated synthetically.

## Why it exists

Audio teams can lose time reviewing broken exports, inconsistent delivery formats and duplicated assets. This tool produces a review queue without rewriting source audio. It bridges Python tooling and an audio-production workflow, and provides a concrete codebase to discuss in an interview.

## Features

- Recursive WAV scanning with deterministic ordering and relative paths.
- Integer PCM support: 8, 16, 24 and 32 bits, with explicit decoding of signed 24-bit samples.
- Duration, sample rate, channel count, bit depth, peak and RMS dBFS, and per-channel DC offset.
- Flags for digital silence, empty/truncated files, PCM rail hits, naming and format inconsistencies.
- Exact duplicate detection using SHA-256.
- JSON manifest and a standalone HTML report with a status filter.
- Bounded PCM read chunks, atomic report writes, escaped HTML and rejection of symlinks outside the asset directory.
- No external packages; Python 3.11+ recommended.

## Run

```bash
python generate_demo.py
python audio_inspector.py assets --json-report report.json --html-report report.html
python -m unittest discover -s . -v
```

Open `report.html` in a browser to review the demo. The demo intentionally includes an invalid WAV, so the inspection command exits with code 2 while still writing the report.

For your own audio:

```bash
python audio_inspector.py /path/to/assets --json-report /path/to/report.json --html-report /path/to/report.html --strict
```

Exit codes: 0 = no errors (warnings allowed by default); 1 = warnings/duplicates under strict mode; 2 = invalid root, unreadable asset or report-writing error.

## Design choices

Source audio is read only. Reports use paths relative to the asset root, so they can travel with the project. A malformed asset becomes an individual error rather than aborting the rest of the scan. Exact hashes identify byte-identical files; they do not compare perceptual similarity. Silence is represented by null dBFS instead of a nonstandard JSON infinity value.

Rail hits indicate clipping risk, not proof of audible distortion. DC offset and format thresholds are project defaults, not universal acceptance standards. Review the flags before deciding whether to re-export audio.

## Limitations

Only uncompressed integer PCM WAV is supported; IEEE float WAV, compressed audio and metadata-only containers are not supported. The tool does not measure LUFS or true peak, classify music/SFX, normalize audio, implement Wwise/WAAPI, or integrate with a game engine. A production pipeline would need project-configurable thresholds, asset ownership, performance benchmarks and real-world fixture validation.

## Interview walkthrough

1. Generate fixtures and explain which problems each fixture represents.
2. Run inspection; explain why the command returns 2 but still writes reports.
3. Show the report, duplicate group and a malformed-file error.
4. Explain 24-bit signed decoding, dBFS normalization and the limitations of clipping heuristics.
5. Run the tests, then inspect the source-file preservation and symlink-boundary tests.
6. Discuss a future Wwise handoff based on the manifest. No Wwise implementation is claimed.

## Project status

This is a portfolio prototype, with synthetic fixtures and an automated test suite. It has not been validated in a production audio pipeline.

License: MIT.
