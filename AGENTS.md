# Agent04 Local Photo Manager Governance

Scope: this repository.

The project indexes and retrieves approved local image collections. Its README,
current backend contracts, runtime configuration schema, entity registry, and
tests are local authority.

## Local boundaries

- Local photo paths, image bytes, face/entity metadata, and derived indexes are
  private data. Do not expose them in logs, fixtures, screenshots, prompts, or
  Web output beyond the approved task.
- External image or query inference is allowed only through a registered
  product-runtime route and only for that route's approved content. Do not add a
  provider, fallback, or broader egress in project governance.
- Embeddings, captions, face matches, and model interpretations are retrieval
  candidates, not factual identity authority.
- Indexing must not delete, move, rename, or edit source photos. Apple Photos and
  external libraries remain read-only unless TZ separately approves mutation.
- Agent04's publishing surface may change only for an approved route delta;
  shared Web navigation and platform styling remain outside this scope.

## Verification and acceptance

Use `pyproject.toml` and current tests to select focused runtime-config security,
indexing, entity-query, source-media, or Agent04 frontend checks for the affected
contract. Apply lint only to the changed Python surface.

The root pytest suite is a Level 4 or approved release gate, not an ordinary
completion default. Completion must prove source media stayed unchanged,
sensitive values were not exposed, and unavailable external inference was
reported as unverified rather than simulated.
