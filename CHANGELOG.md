# Changelog

All notable changes to Rig Bridge are documented here.

## [Unreleased]

## [0.1.65] - 2026-07-24

### Fixed

- Added the missing humanoid segment constants used by the interactive canvas
- Added the missing 3D View utility import used by viewport armature picking
- Removed stale dynamic import guards and unused imports that obscured static analysis

### Changed

- Added a source-level Ruff gate for Python syntax and undefined-name checks

## [0.1.64] - 2026-07-21

### Changed

- Removed every call to operators and runtime properties owned by other add-ons
- Kept rig-family recognition as passive input-data matching handled by Rig Bridge itself
- Initialize the humanoid canvas draw handler only after the user opens its operator

### Removed

- Add-on registration timers and the unused embedded-panel draw-handler path
- Obsolete native retarget helpers and translations tied to the removed integration

## [0.1.63] - 2026-07-16

### Changed

- Renamed the public GitHub repository from `humanoid-remap-studio` to `rig-bridge`
- Updated the Blender Extensions website metadata to the canonical `https://github.com/qw424886884/rig-bridge` URL
- Kept the extension ID, Python package name, schema IDs, and generated-action provenance marker stable for compatibility

## [0.1.62] - 2026-07-16

### Changed

- Renamed the user-facing product from Humanoid Remap Studio to Rig Bridge
- Added the Chinese product name 动作搬运工 and a clearer plain-language tagline
- Kept the extension ID, package name, repository URL, schema IDs, and generated-action provenance marker stable for compatibility

## [0.1.61] - 2026-07-15

### Added

- Simplified Chinese localization through Blender's translation API
- Focused runtime modules for actions, recognition, canvas drawing, retargeting, operators, UI, and translations

### Changed

- Made all user-facing source text English by default
- Switched extension internals to explicit relative imports and a thin package entry point

### Removed

- Manual module reload code; development reloads now follow Blender's official extension workflow

## [0.1.60] - 2026-07-15

### Added

- Production-validated MMD FK preset, including Japanese kana and full-width digit matching
- Dual-root MMD/ARP mapping for motion center and lower-body pelvis controls
- Symmetric paired-leg topology solver for anonymous humanoid skeletons
- Blender stress harness that independently scrambles both armature namespaces
- Name-free anatomical-frame transfer for rigs with different rest poses and bone axes
- Bilateral branch landmarks that infer hips, chest, limbs, and body axes without bone names
- Name-free finger classification using thumb direction, hand-local ordering, and palm-helper detection
- Persistent Blender generalization matrix covering four unrelated source/target skeleton pairs

### Changed

- Prefer coherent topology matches over semantic-name guesses when no preset is available
- Require unique, ancestor-consistent core chains before accepting topology recognition
- Derive the lateral center from paired upper-leg joints instead of accessory extents
- Score complete arm chains and reject accessory leaf fans when finding the trunk and limbs
- Preserve target proportions while transferring root displacement from the evaluated hip joint
- Infer left/right from coherent spatial landmarks when scrambled names provide no side evidence
- Stop anonymous torso and foot chains at structural head and toe terminals instead of accessory fans

### Fixed

- MMD leg chains being shifted by one bone (`knee -> thigh`, `ankle -> shin`, `toe -> foot`)
- Lower-body and spine distortion caused by omitting the source pelvis branch
- Multiple Auto-Rig Pro root entries being marked as retarget roots
- Stale high-confidence auto candidates blocking improved recognition on subsequent runs
- Static source toe bones receiving a large artificial Auto-Rig Pro rest-offset bake
- Anonymous crouched rigs choosing depth as the lateral axis and swapping arms with legs
- Palm helper bones replacing real proximal phalanges, or proximal phalanges being stripped as helpers
- Auto-Rig Pro-shaped targets forcing the native ARP route when Auto-Rig Pro is not installed

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
