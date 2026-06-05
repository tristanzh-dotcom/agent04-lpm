# Agent04 Source Quality Delta Design

## Goal

Avoid unnecessary vision-model reindexing when an Apple Photos asset switches between a local original and a derivative preview, while still exposing the library's current original-versus-preview inventory in the Agent04 header.

## Business Rule

Apple Photos `asset_id` and `local_identifier` define photo identity. When either stable identity matches an existing SQLite row, a change in `source_path`, file bytes, MD5, or mtime is treated as a source-quality transition, not a semantic photo change.

## API Contract

`GET /api/index/status` returns a `source_quality` object:

```json
{
  "source_quality": {
    "original_count": 12340,
    "derivative_count": 2459
  }
}
```

`GET /api/index/delta` also returns `source_quality` and optional transition counts:

```json
{
  "source_quality": {
    "original_count": 12340,
    "derivative_count": 2459,
    "source_file_changed_count": 120
  }
}
```

`source_file_changed_count` is informational. It does not contribute to `changed_count` or `has_delta`.

## Data Flow

`ApplePhotosPeopleBridge.iter_image_asset_resources()` already chooses the best local source for each Apple Photos asset and returns `source_kind` as `original` or `derivative`. `ArkSearchService` will count those values to build `source_quality`. The Web publishing server will pass the object through `/api/agent04/status`, and the Agent04 header will render `索引 X 张 · 原图 Y · 预览图 Z`.

## Non-Goals

Do not label individual search result cards as original or preview. Do not trigger PhotoKit original downloads from result rendering. Do not call Ark or DeepSeek for source-quality statistics.

## Testing

Tests must prove that an asset matched by stable identity is not marked changed when `source_path` changes between derivative and original. Tests must also prove that source-quality counts reach `/api/agent04/status` and the header label.
