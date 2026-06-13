# Agent04 Person Register Order Design

## Scope

This is an Agent04 Web-visible publishing change inside the embedded static frontend at `frontend/agent04`. It does not change Apple Photos reading, face indexing, profile persistence, or shared Web platform sidebar behavior.

## User Problem

In daily use, checking and finding available people is more frequent than adding new people. The current register panel starts with `新增人物`, which optimizes for the less common creation path and hides Apple Photos inherited people below manual profile management.

## UX Contract

The `人物入库` panel must present content in this order:

1. `Apple Photos 只读继承`
   - First visible people group after profile data loads.
   - Read-only source copied from macOS Photos people/pet recognition.
   - No delete action.
2. `人物库管理`
   - Second people group for manually registered Agent04 profiles.
   - Delete and reindex actions remain available.
3. `新增人物`
   - Last section in the panel.
   - Used for the less frequent manual face-vector registration flow.

## Data Flow

- `loadProfiles()` still fetches `GET /api/people/profiles`.
- The same `apple_photos` vs manual source split remains.
- Rendering order changes only: Apple Photos profiles first, manual profiles second.

## Tests

- Static frontend test: `limb-profile-board` appears before `limb-register-form-card` in the register panel.
- Static frontend test: `loadProfiles()` renders `Apple Photos 只读继承` before `人物库管理`.
- Existing frontend tests continue to verify avatar cards, delete controls, read-only badges, and profile refresh behavior.
