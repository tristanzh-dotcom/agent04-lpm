# 本地图像检索

## Apple Photos 启动配置

本项目当前底层图片库切换为 Mac 原生 Apple Photos。运行前请把 `LIMB_PHOTO_ROOT` 指向照片图库包内部的 `originals` 目录：

```bash
export LIMB_PHOTO_ROOT="/Users/你的用户名/Pictures/Photos Library.photoslibrary/originals"
```

请将 `你的用户名` 替换为真实 Mac 账户名。若你的图库名称是中文“照片图库”，路径应调整为：

```bash
export LIMB_PHOTO_ROOT="/Users/你的用户名/Pictures/照片图库.photoslibrary/originals"
```

`originals` 是 Apple Photos/iCloud 同步原图的物理目录。扫描引擎会递归扫描该目录，保持原有增量机制：只处理新增文件或 `modify_time` 变化的文件。

## 常用命令

安装依赖：

```bash
python3 -m pip install -r backend/requirements.txt
```

扫描 Apple Photos 原图目录：

```bash
python3 -m backend.scan_engine "$LIMB_PHOTO_ROOT"
```

启动后端：

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek Key"
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## 模型与密钥配置规则

本项目默认不使用 GPT-5.5。核心链路为：

- 视觉索引：火山方舟 Ark 视觉模型 / Endpoint。
- 中文检索意图理解：DeepSeek V4 Pro。
- 本地召回：SQLite FTS + Jieba。

所有 API Key 必须通过环境变量或本机忽略文件提供，不能写入
`backend/config.py` 或启动脚本。

DeepSeek Query Bridge 是增强层，不是硬依赖：

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
export DEEPSEEK_MODEL="deepseek-v4-pro"
```

如果 `DEEPSEEK_API_KEY` 未设置、Key 失效、余额不足、网络失败，或 DeepSeek 返回异常，
后端会自动回退到默认本地基座检索：`SQLite FTS5 + Jieba + 本地人物库规则`。
该回退不会阻断搜索，但复杂自然语言 query 的召回质量会低于 DeepSeek 可用时。

启动前端：

```bash
cd frontend
python3 -m http.server 3000
```
