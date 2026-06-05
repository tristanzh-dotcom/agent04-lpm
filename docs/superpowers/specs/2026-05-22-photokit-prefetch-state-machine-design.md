# Agent04 PhotoKit 原图预热状态机设计

## 目标

在不破坏当前 Ark + SQLite + 人脸向量检索闭环的前提下，新增 PhotoKit 原图按需预热状态机。搜索接口必须继续快速返回缩略图结果，同时把命中的 `localIdentifier` 交给后台任务预热高清原图。

## 硬边界

1. 如果高清原图已经存在于本地物理磁盘，且文件大小大于 0 字节，代码必须直接跳过，严禁调用 PhotoKit 网络相关 API。
2. 代码层不主动删除原图或释放磁盘，磁盘优化交给 macOS。
3. 搜索主线程不等待 PhotoKit、不等待 iCloud、不等待原图下载。
4. 旧的 1181 张 `path` 记录继续兼容，不能因为新增 PhotoKit 字段而失效。
5. 新 PhotoKit 记录使用 `localIdentifier`，并用 `asset_id = sha1(localIdentifier)` 作为安全文件名和 API 主键。

## 数据模型

在 `photos` 表中增加兼容字段：

- `asset_id TEXT`
- `local_identifier TEXT`
- `original_path TEXT`
- `thumbnail_path TEXT`
- `source TEXT`

旧数据迁移策略：

- `source = filesystem`
- `original_path = path`
- `asset_id/local_identifier` 为空

新 PhotoKit 数据：

- `source = photokit`
- `asset_id = sha1(localIdentifier)`
- `local_identifier = PhotoKit localIdentifier`
- `original_path` 如果可映射则保存，否则为空
- `thumbnail_path = .cache/thumbnails/{asset_id}.jpg`

## 后端状态机

`backend/apple_photos_bridge.py` 提供：

- `stable_asset_id(local_identifier)`
- `PhotoKitOriginalPrefetcher`
- `prefetch_originals_if_needed(identifiers, path_resolver=None)`

状态机：

```text
identifier
  -> resolve original_path
  -> exists && size > 0 ?
      yes: local-ready-skip
      no: PhotoKit requestImageDataAndOrientation(... networkAccessAllowed=True, synchronous=False)
```

测试环境通过 fake resolver 和 fake PhotoKit requester 验证状态机，不依赖真实 macOS Photos 权限。

## 搜索接口

`POST /api/search`：

1. 先用当前 DeepSeek Query Bridge + SQLite + FaceVector 逻辑得到结果。
2. 立即返回 JSONResponse。
3. 如果结果中含有 `local_identifier`，用 `BackgroundTasks.add_task()` 调用 `prefetch_originals_if_needed()`。
4. 响应体仍保持数组，前端兼容。

## 前端

`frontend/agent04/app.js`：

- 优先使用 `item.url` 打开大图。
- 如果后续 PhotoKit 记录返回 `/api/assets/{asset_id}/image`，LightBox 无需额外改视觉结构。

## 验证

1. 单元测试确保已有本地原图时不调用 PhotoKit requester。
2. 单元测试确保缺失原图时才调用 requester。
3. 单元测试确保 `/api/search` 使用 BackgroundTasks 调度预热，但响应仍立即返回数组。
4. 当前 1000 多张旧索引小样本检索必须继续返回。
