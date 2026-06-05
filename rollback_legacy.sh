#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="/Users/tristanzh/agent/Local-photo-model"
ARCHIVE_DIR="$TARGET_DIR/_archive_legacy"

mkdir -p "$TARGET_DIR/docs/handovers"

if [[ -f "$ARCHIVE_DIR/HANDOFF.md" ]]; then
  mv "$ARCHIVE_DIR/HANDOFF.md" "$TARGET_DIR/HANDOFF.md"
fi
if [[ -f "$ARCHIVE_DIR/PROJECT_MEMORY.md" ]]; then
  mv "$ARCHIVE_DIR/PROJECT_MEMORY.md" "$TARGET_DIR/PROJECT_MEMORY.md"
fi
if [[ -f "$ARCHIVE_DIR/PROJECT_RULES.md" ]]; then
  mv "$ARCHIVE_DIR/PROJECT_RULES.md" "$TARGET_DIR/PROJECT_RULES.md"
fi
if [[ -f "$ARCHIVE_DIR/CHANGELOG.md" ]]; then
  mv "$ARCHIVE_DIR/CHANGELOG.md" "$TARGET_DIR/CHANGELOG.md"
fi
if [[ -f "$ARCHIVE_DIR/NEXT_STEPS.md" ]]; then
  mv "$ARCHIVE_DIR/NEXT_STEPS.md" "$TARGET_DIR/NEXT_STEPS.md"
fi
if [[ -f "$ARCHIVE_DIR/PROJECT_INDEX.md" ]]; then
  mv "$ARCHIVE_DIR/PROJECT_INDEX.md" "$TARGET_DIR/PROJECT_INDEX.md"
fi
if [[ -f "$ARCHIVE_DIR/2026-05-23-agent04-limb-ui-debug-handover.md" ]]; then
  mv "$ARCHIVE_DIR/2026-05-23-agent04-limb-ui-debug-handover.md" "$TARGET_DIR/docs/handovers/2026-05-23-agent04-limb-ui-debug-handover.md"
fi
if [[ -f "$ARCHIVE_DIR/2026-05-24-limb-full-index-and-dynamic-status-handover.md" ]]; then
  mv "$ARCHIVE_DIR/2026-05-24-limb-full-index-and-dynamic-status-handover.md" "$TARGET_DIR/docs/handovers/2026-05-24-limb-full-index-and-dynamic-status-handover.md"
fi
if [[ -f "$ARCHIVE_DIR/2026-05-29-agent04-final-handoff.md" ]]; then
  mv "$ARCHIVE_DIR/2026-05-29-agent04-final-handoff.md" "$TARGET_DIR/docs/handovers/2026-05-29-agent04-final-handoff.md"
fi
if [[ -f "$ARCHIVE_DIR/2026-05-29-agent04-handoff.md" ]]; then
  mv "$ARCHIVE_DIR/2026-05-29-agent04-handoff.md" "$TARGET_DIR/docs/handovers/2026-05-29-agent04-handoff.md"
fi
if [[ -f "$ARCHIVE_DIR/2026-05-29-closeout.md" ]]; then
  mv "$ARCHIVE_DIR/2026-05-29-closeout.md" "$TARGET_DIR/docs/handovers/2026-05-29-closeout.md"
fi
if [[ -f "$TARGET_DIR/AGENTS.md.bak" ]]; then
  mv "$TARGET_DIR/AGENTS.md.bak" "$TARGET_DIR/AGENTS.md"
fi
