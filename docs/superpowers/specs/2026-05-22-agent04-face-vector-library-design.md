# Agent04 Phase 4.2 人脸向量库设计

## 背景

Agent04 当前已经完成 Ark + SQLite FTS5 的本地相册语义检索。该架构能通过豆包视觉模型生成 `description`、`tags`、`colors`，并在本地数据库中做中文全文检索。

当前缺口是“昵称等于具体人”。例如用户输入“小菲”时，现有系统只能把“小菲”扩展为“女性、女孩、合影”等语义关键词，无法保证检索结果中的人物就是小菲本人。

Phase 4.2 目标是新增本地人脸向量库，使用户能够录入昵称和 3-5 张样张，系统提取该人的人脸特征并持久保存。之后用户搜索昵称时，后端用本地人脸向量进行身份匹配。

## 第一性原则

1. 身份识别必须使用人脸 embedding，不再用语义标签模拟身份。
2. Ark 语义索引继续负责场景、物体、动物、颜色、动作等描述性检索。
3. 人脸向量库是独立子系统，不能破坏现有 Ark SQLite 索引和前端发布路由。
4. 用户样张只用于本地向量提取和本地存储，不上传到 DeepSeek 或 Ark。
5. 前端所有交互仍锁定在 `/frontend/agent04/` 右侧工作台，不改左侧 Sidebar。

## 选型

采用 InsightFace 作为本地人脸 embedding 引擎，原因是：

- 成熟、准确、适合家庭相册身份识别。
- 注册阶段和相册补扫阶段都能复用同一套 embedding。
- 向量余弦相似度计算简单，可测试、可解释、可调阈值。

依赖建议：

- `insightface`
- `onnxruntime`
- `opencv-python-headless`
- `numpy`
- `pillow`

## 数据结构

新增本地文件：

- `data/face_profiles.pkl`
- `data/photo_face_index.pkl`

`face_profiles.pkl` 存储昵称向量：

```python
{
    "小菲": {
        "label": "小菲",
        "embedding": np.ndarray,   # L2 normalized
        "sample_count": 5,
        "created_at": "...",
        "updated_at": "..."
    }
}
```

`photo_face_index.pkl` 存储相册照片中的原始人脸向量：

```python
{
    "/abs/photo/path.jpeg": {
        "modify_time": 1710000000.0,
        "faces": [
            {
                "embedding": np.ndarray,   # L2 normalized
                "bbox": [x1, y1, x2, y2],
                "det_score": 0.98
            }
        ]
    }
}
```

## 后端模块

新增 `backend/face_engine.py`。

职责：

1. 初始化 InsightFace。
2. 从上传样张中提取最大或最清晰人脸。
3. 对 3-5 张样张求平均向量并归一化。
4. 增量扫描相册照片，建立 `photo_face_index.pkl`。
5. 根据昵称向量匹配照片中的人脸向量，返回匹配路径和分数。

核心类：

- `FaceVectorEngine`
  - `register_profile(label, images) -> dict`
  - `scan_photo_directory(photo_root) -> dict`
  - `match_label(label, candidate_paths=None, threshold=0.45, limit=100) -> list`
  - `list_profiles() -> list`

默认阈值先设为 `0.45`，通过环境变量 `LIMB_FACE_THRESHOLD` 覆盖。InsightFace 家庭相册场景通常 0.35-0.55 之间需要实测微调。

## API 设计

在 `backend/ark_main.py` 中新增或扩展：

### `POST /api/face/register`

FormData:

- `label`: 字符串，例如 `小菲`
- `files`: 3-5 张图片

返回：

```json
{
  "status": "success",
  "label": "小菲",
  "sample_count": 5,
  "message": "成员 [小菲] 已成功精确锚定入库"
}
```

错误：

- 样张少于 3 张：`400`
- 未检测到人脸：`400`
- 多张样张均失败：`400`

### `GET /api/face/profiles`

返回当前已注册昵称列表：

```json
[
  {"label": "小菲", "sample_count": 5, "updated_at": "..."}
]
```

### `POST /api/face/reindex`

触发相册人脸索引增量扫描。可先实现同步版本，后续再升级为后台任务。

入参：

```json
{"photo_root": "/Users/tristanzh/Pictures/照片图库.photoslibrary/originals"}
```

返回：

```json
{"indexed": 1181, "skipped": 1000, "failed": 6}
```

### `POST /api/search`

保留现有接口，不破坏前端。

新增逻辑：

1. 从用户 query 中识别已注册昵称。
2. 如果 query 只有昵称或主要是昵称，则直接从 `photo_face_index.pkl` 召回人脸匹配照片。
3. 如果 query 同时包含昵称和语义条件，例如“小菲和狗狗的照片”，则：
   - 先用 Ark SQLite 搜索“狗狗/狗/宠物”等非身份关键词，得到候选照片。
   - 再用小菲的人脸向量过滤候选照片。
4. 返回仍保持当前富对象数组：

```json
[
  {
    "md5": "...",
    "path": "...",
    "url": "http://127.0.0.1:8004/photos/...",
    "thumbnail_url": "http://127.0.0.1:8004/thumbnails/....jpg",
    "description": "...",
    "tags": ["..."],
    "colors": ["..."],
    "face_score": 0.62,
    "matched_labels": ["小菲"]
  }
]
```

## 前端设计

仅修改 `/frontend/agent04/`。

新增一个右侧工作台内的“人物入库”面板，不触碰全局 Sidebar。

交互：

1. 顶部增加两个局部 Tab：
   - `检索`
   - `人物入库`
2. 人物入库面板包含：
   - 昵称输入框
   - 3-5 张图片拖拽/选择上传区
   - 样张缩略图预览
   - “开始学习”按钮
   - 已注册人物列表
3. 上传提交必须 `preventDefault()`，使用 `fetch` 发送 FormData 到 `/api/face/register`。
4. 注册成功后显示：
   - `成员 [小菲] 已成功精确锚定入库`
   - 提示用户执行或等待“相册人脸索引补扫”
5. 搜索栏保持原有体验。用户输入“小菲”或“小菲和狗狗”时，后端自动使用人脸向量。

## 测试计划

遵守 TDD。

后端测试：

1. `FaceVectorEngine` 能把多张样张向量平均并归一化。
2. 注册样张少于 3 张返回 400。
3. 已注册昵称能在搜索 query 中被识别。
4. “小菲和狗狗”先做语义候选，再做人脸过滤。
5. 没有相册人脸索引时返回清晰错误或空结果提示，不让前端误判为系统坏了。

前端测试：

1. 入库表单不会触发页面刷新。
2. 上传 3-5 张图片能生成预览。
3. 成功后状态反馈正确。
4. 搜索结果能展示 `matched_labels` 和 `face_score`。

## 风险与边界

1. 首次相册人脸补扫需要本地 CPU 时间，可能比 Ark 文本索引更慢，但不产生云端费用。
2. Apple Photos 中 HEIC 图片可能需要 Pillow 或系统解码支持；无法读取的图片应记录失败并跳过。
3. 人脸阈值需要实测调参。初始值 `0.45` 只是保守起点。
4. 如果样张中有多人脸，默认选最大人脸；前端后续可增加“裁切/确认人脸”能力。
5. 该阶段不重新引入 Chinese-CLIP。

## 实施顺序

1. 写失败测试：后端人脸向量注册、匹配、搜索融合。
2. 实现 `backend/face_engine.py`。
3. 扩展 `backend/ark_main.py` API 和搜索融合逻辑。
4. 扩展 `frontend/agent04/` 入库面板。
5. 更新依赖和启动脚本。
6. 运行单元测试、compileall、浏览器手测。
