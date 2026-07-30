# Imported UI rhythm-only status

## Background

The imported vortex frontdesk UI still showed auxiliary state labels in the center status capsule and bottom voice bar. These labels competed with the visual style and duplicated the actual visitor recognition and avatar reply content.

## Root Cause

The UI mapped voice phases to default text labels and rendered those labels separately from the real transcript fields. Even after simplifying the bottom bar, the center orb status capsule still rendered the phase label and old static chunks remained in the deployed asset directory.

## Changes

- Replaced non-transcript status labels with animated rhythm bars in the center orb status capsule.
- Kept bottom text rendering limited to real visitor recognition text or avatar reply text.
- Removed default phase labels from the imported UI voice state model so they are not bundled as visible fallbacks.
- Refreshed the static `imported-ui` output and removed obsolete hashed chunks.

## Validation

- `node .\node_modules\next\dist\bin\next build`
- `rg` check for old visible status labels in source and static output
- `git diff --check`
