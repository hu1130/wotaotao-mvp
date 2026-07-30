# Imported UI remove orb rhythm

## Background

The vortex frontdesk center area still rendered a rhythm capsule directly under the fluid orb. The user wanted the area under the vortex to stay clean and keep rhythm feedback in the bottom voice bar only.

## Changes

- Removed the center orb rhythm capsule from `VoiceOrbVisual`.
- Kept the bottom voice control rhythm bars and transcript rendering unchanged.
- Rebuilt the static `imported-ui` assets for deployment.

## Validation

- `node .\node_modules\next\dist\bin\next build`
- Checked that the static page still contains bottom `sound-bar` output.
- Checked that the center status capsule marker is no longer present.
- `git diff --check`
