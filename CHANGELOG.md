# Changelog

All notable changes to Humanoid Remap Studio are documented here.

## [0.1.59] - 2026-07-13

### Added

- Single and collection batch source modes
- Strict humanoid, action, rest-pose, and forward-axis batch gates
- Preset-first recognition with semantic and topology fallback
- Persistent batch actions that survive save and reload
- Bilingual public documentation and Blender Extensions packaging metadata

### Changed

- Simplified the main sidebar workflow to detection, in-place selection, execution, and cleanup
- Restored the add-on to its independent `Remap` sidebar category
- Aligned package and runtime versions at `0.1.59`

### Fixed

- Source animation loss during detection
- Left-arm twist and forward-axis mismatch cases
- Duplicate root-motion and in-place result generation
- Incomplete cleanup and stale batch action records
- Batch summary being replaced by the final single-pair summary
