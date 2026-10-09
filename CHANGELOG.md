# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-09

First public release (published as `pytuneslib`).

### Added

- Scan a music folder (MP3, M4A/ALAC/AAC, WAV, AIFF) and write `iTunes Music Library.xml`.
- Write `iTunes Library.itl` for iTunes 12.13 (AES-128-ECB on the first 100 KB, zlib level 1, little-endian chunks).
- Read `.itl` and XML libraries back into a `Library` model (`Track`, `Playlist`, `Library`).
- Command-line interface: `build` with `--no-itl`, `--include-unsupported`, `--kind-locale en|es`.
- Refusal to write into the default iTunes library folder.
- Tests with a synthetic music library generated with ffmpeg.

### Known limitations

- FLAC, OGG, Opus and WMA are skipped unless `--include-unsupported` is given; iTunes cannot play them.
- Artwork, play history, skip history, smart playlists and folder playlists are not modeled.
- Tested only with iTunes 12.13.11.1 on Windows (Microsoft Store build).
