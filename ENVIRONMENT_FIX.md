# 环境修复记录

## 问题

自定义编译的 Python 3.12 缺少 `_ctypes` 模块，导致：
- ChromaDB 无法导入
- pandas 无法导入
- 项目代码无法完整运行

## 根因

- `/home/caros/.python3.12/bin/python3` — 源码编译时缺少 `libffi-dev`，`_ctypes` 扩展未编译
- 项目 `.venv` 目录为空（之前用 broken Python 创建失败）

## 修复方案

### 1. 创建新虚拟环境（Python 3.8）

```bash
cd /data/schematic_agent
rm -rf .venv
virtualenv -p /usr/bin/python3.8 .venv
```

### 2. 修复 sqlite3 兼容性

Ubuntu 20.04 系统 sqlite3 (3.31.1) < ChromaDB 要求 (3.35.0)

```bash
.venv/bin/pip install pysqlite3-binary
```

创建 `.venv/lib/python3.8/site-packages/chroma_sqlite_fix.pth`：

```python
import sys; exec("try:\n    from pysqlite3 import dbapi2 as _sqlite3\n    sys.modules['sqlite3'] = _sqlite3\nexcept ImportError:\n    pass\n")
```

此文件在 Python 启动时自动执行，用 pysqlite3 替换系统 sqlite3。

### 3. 修复 posthog 兼容性

Python 3.8 不支持 `dict[str, FeatureFlag]` (Python 3.9+ 语法)：

```bash
.venv/bin/pip install 'posthog<3.0'
```

### 4. 安装项目依赖

```bash
.venv/bin/pip install streamlit neo4j chromadb pymupdf pandas openpyxl
```

### 5. Python 3.8 类型注解兼容

给 `knowledge_router.py` 添加 `from __future__ import annotations`，使 `list[...]` 等 PEP 585 语法在 Python 3.8 下正常工作。

## 验证

```bash
.venv/bin/python -c "
import chromadb
print('chromadb:', chromadb.__version__)

client = chromadb.Client(chromadb.config.Settings(anonymized_telemetry=False))
col = client.get_or_create_collection('test')
col.add(documents=['hello'], ids=['1'])
print('ChromaDB OK')
"
```

## 当前状态

| 组件 | 状态 |
|------|------|
| Python | 3.8.10 (系统) |
| ChromaDB | 0.5.23 ✅ |
| Streamlit | ✅ |
| Neo4j driver | ✅ |
| PyMuPDF | ✅ |
| pandas | ✅ |

## 使用方法

```bash
cd /data/schematic_agent
source .venv/bin/activate
python test_phase1.py
```
