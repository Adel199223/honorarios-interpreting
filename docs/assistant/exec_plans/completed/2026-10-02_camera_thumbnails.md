# Recognizable Camera photo thumbnails

## Scope and provenance

The user reports that the configured Camera chooser shows only filenames and asks to see photos at a useful medium/large size before choosing. Reuse the attached Photos/readiness candidate based on `a0ed383`, preserving the accepted 808-test sent-summary/usage work and all earlier local/private changes. This scope authorizes local photo previews and chooser testing, with no OCR/provider call, fee preparation, Gmail/history mutation, publication or LegalPDF integration.

## Design and contracts

Add bounded fingerprint-bound local thumbnail rendering with correct EXIF orientation and no embedded metadata. Retain original root/path/type/size/freshness guards, and select original bytes through the existing file endpoint. Keep directory listing metadata-only. Use a bounded memory cache and decoder limits. Show a responsive grid with large recognizable previews, readable filenames, loading/error fallback and keyboard selection. Limit concurrent/visible preview work and clean up stale or cancelled loads without changing the active request. Keep the separate Review source action and unfinished-work protection.

## Acceptance sequence

Backend and frontend changes have separate owners and independent review. Preserve exact beforeimages and incremental hashes. Run meaningful focused checks, then final candidate/saved Full in the pinned environment, covering the explicit portable suite and four isolated workflows. Verify the ordinary browser chooser in a disposable synthetic runtime and the user's connected Camera, including visible pictures, orientation, search, cancellation and original selection. Preserve all private records/artifacts and pending browser work; take a final screenshot and leave the chooser ready. Keep a precise account of any tooling limitation or remaining work.

## Progress — 2026-10-02

The existing chooser uses filename-only buttons. The current app is stopped on a sent duplicate and retains older unfinished browser work. No extra review/provider read is needed for this visual improvement. Implementation is proceeding in the existing candidate, while the root owns guidance and live acceptance.

## Completion

The [Camera thumbnail plan](2026-10-02_camera_thumbnails.md) is complete locally and applied to the usual saved app. **Add source file** opens the configured Camera folder as a responsive grid of large, correctly oriented previews with filenames and sizes. Visible previews load locally in a bounded queue and memory cache; selecting a tile still reads the guarded original with its capture date/GPS intact. Search, pagination, cancellation, stale-load cleanup and keyboard selection are covered. No AI call occurs until the separate source-review action.

The live phone check exposed a high-resolution JPEG limitation. The follow-up supports very high resolution baseline JPEGs through bounded reduced decoding, without changing global Pillow limits or altering originals. An unreadable/unsupported preview remains selectable as an original. Independent review passed; focused coverage includes 35 Camera UI tests, 226 UI tests and 44 backend tests. Candidate and saved Full each passed **828 public tests and four isolated workflows** after the final change.

Ordinary browser acceptance used fictional portrait, EXIF-rotated and corrupt images, then the connected phone Camera. The updated chooser is left open with real previews. All 1,709 protected config/data/output files and 53 fictional originals remain byte-identical; no new protected files were added. Earlier unfinished browser work remains saved. Exact beforeimages, incremental hashes, tests and screenshots are under ignored `tmp/camera-thumbnails-2026-10-02/`. No provider, fee PDF, Gmail, history, dependency, publication or LegalPDF integration operation occurred. The usual server remains at 8878. Earlier sections below are historical checkpoints.

