# Apple Photos Entity Inheritance Design

## Goal

让 LIMB 继承 macOS Photos 已经完成的人物/宠物聚类结果，把“人物入库”从重复训练升级为“同步 Apple 原生识别结果 + LIMB 手动别名和业务标签扩展”。

## Current Finding

当前真实图库路径为 `/Users/tristanzh/Pictures/Photos Library.photoslibrary`。只读探针确认：

- `database/Photos.sqlite` 存在可读的 `ZPERSON`、`ZDETECTEDFACE`、`ZASSET` 表。
- `ZPERSON` 保存已命名人物/宠物聚类。
- `ZDETECTEDFACE.ZPERSONFORFACE` 可关联 `ZPERSON.Z_PK`。
- `ZDETECTEDFACE.ZASSETFORFACE` 可关联 `ZASSET.Z_PK`。
- `ZASSET.ZDIRECTORY + ZASSET.ZFILENAME` 可反推出 `originals/<directory>/<filename>` 物理路径。

本机当前探针结果：已命名聚类 7 个，包括 `妈`、`爸`、`菜`、`小米`、`王女士`、`安哥拉`、`Biu`。

## Boundary Principles

- 只读 Apple Photos 私有数据库，绝不写回 `Photos.sqlite`。
- Apple 私有 schema 不作为不可变契约，所有读取逻辑必须可探测、可失败、可降级。
- LIMB 自己维护扩展层：别名、家庭关系、业务物体标签、人工纠偏结果。
- 现阶段先做探针和只读桥接，不立即改变现有搜索排序和前端布局。

## Implemented Probe

- `backend.apple_photos_bridge.ApplePhotosPeopleBridge`
  - `list_named_people()`：列出 Apple Photos 已命名聚类。
  - `iter_person_asset_links()`：输出人物/宠物标签与原图路径映射。
- `backend/probe_apple_photos_people.py`
  - 命令行只读探针，可输出人类可读文本或 JSON。

## Next Architecture

建议新增 LIMB 实体索引表：

```text
photo_entities
- original_path
- asset_uuid
- label
- entity_type: person | pet | object | scene
- source: apple_photos | limb_manual | ark_vlm
- confidence
- updated_at

identity_aliases
- canonical_label
- alias
- source
- updated_at
```

搜索时优先级：

1. DeepSeek 将用户查询拆成实体约束、场景约束、时间地点约束。
2. Apple/LIMB 实体索引先过滤人物、宠物和合照条件。
3. Ark SQLite FTS 再过滤场景、动作、物体和颜色。
4. 若 Apple 实体命中但场景未命中，允许显式降级返回人物照片，并提示“场景未命中”。

## Verification

- 单元测试覆盖合成 Photos.sqlite 的人物读取和路径映射。
- 真实探针已在本机 Photos Library 上只读运行，确认可读取 7 个已命名聚类。

## Risks

- `Photos.sqlite` 是 Apple 私有 schema，macOS 升级可能改变字段名或关系。
- 目前只确认人物聚类可读；宠物聚类可能复用 `ZPERSON`，也可能在不同系统版本有不同 `ZDETECTIONTYPE` 语义，需要后续实测。
- 当前实现不写入 LIMB 搜索索引，只提供继承数据源。
