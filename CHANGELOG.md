# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-07-07

### Added
- `scrape-fb schema`: prints the `fetch` output object schema (field name, JSON type, one-line meaning), offline and always exit 0; `--json` emits JSON Schema (draft 2020-12). Anchored on `Post.to_dict()`'s actual output keys, not the dataclass fields, so it can't mis-document `raw` as always-present.
- Every `fetch`/`login`/`status`/`doctor` flag now has a `--help` string with its human-readable default, so `--help` is authoritative standalone without reading source.

### Changed
- No behavior change to `login`/`status`/`setup`/`doctor`/`fetch` themselves — additive only.

## [0.1.0] - 2026-07-05

### Added
- Initial release: `scrape-fb login` / `status` / `setup` / `doctor` / `fetch`.
- Logged-in Facebook timeline scraping via GraphQL XHR observation (no token replay).
- `--limit`, `--since`/`--until` retrieval with stop-reason reporting.
- JSON and NDJSON output formats.
- Python API: `FacebookScraper`, `Post`, `Media`, `LinkAttachment`.

[Unreleased]: https://github.com/tjdwls101010/Scraper-for-Facebook/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/tjdwls101010/Scraper-for-Facebook/releases/tag/v0.2.0
[0.1.0]: https://github.com/tjdwls101010/Scraper-for-Facebook/releases/tag/v0.1.0
