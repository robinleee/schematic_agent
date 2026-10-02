# 后端 REST API 接口文档

## 1. 概述

本文档定义硬件 AI 专家系统的后端 REST API 接口规范。后端基于 FastAPI 实现，提供 RESTful API 和 WebSocket 支持。

---

## 2. API 基础信息

### 2.1 服务地址

```
开发环境: http://localhost:8501
生产环境: http://<server>:8501
```

### 2.2 通用约定

- **协议**: HTTP/1.1 + WebSocket
- **数据格式**: JSON
- **字符编码**: UTF-8
- **时间格式**: ISO 8601 (`YYYY-MM-DDTHH:mm:ss.sssZ`)
- **API 前缀**: `/api/v1`

### 2.3 通用响应格式

```typescript
// 成功响应
interface SuccessResponse<T> {
  success: true;
  data: T;
  message?: string;
  timestamp: string;
}

// 错误响应
interface ErrorResponse {
  success: false;
  error: {
    code: string;
    message: string;
    details?: Record<string, any>;
  };
  timestamp: string;
}
```

### 2.4 错误码定义

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| `INVALID_REQUEST` | 400 | 请求参数无效 |
| `UNAUTHORIZED` | 401 | 未授权 |
| `FORBIDDEN` | 403 | 禁止访问 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `CONFLICT` | 409 | 资源冲突 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |
| `SERVICE_UNAVAILABLE` | 503 | 服务不可用（Neo4j/Ollama 未连接） |

---

## 3. 数据模型 (Pydantic Schemas)

### 3.1 基础模型

```python
# api/schemas/base.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any

class BaseResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None
    timestamp: str = datetime.now().isoformat()

class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20
```

### 3.2 对话模型

```python
# api/schemas/chat.py
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum

class TaskType(str, Enum):
    REVIEW = "review"
    DIAGNOSIS = "diagnosis"
    QUERY = "query"
    AUTO = "auto"

class ReasoningStep(BaseModel):
    """推理步骤"""
    step_id: int
    thought: str
    action: str
    action_input: Dict[str, Any]
    observation: str
    timestamp: str
    duration_ms: Optional[int] = None
    is_error: bool = False

class ChatRequest(BaseModel):
    """对话请求"""
    message: str
    task_type: Optional[TaskType] = TaskType.AUTO
    context: Optional[Dict[str, Any]] = None

class ChatResult(BaseModel):
    """对话结果"""
    status: str  # success, timeout, error
    task_type: str
    report: str  # Markdown 格式报告
    execution_trace: List[ReasoningStep]
    tool_call_count: int
    timestamp: str

class ChatResponse(BaseResponse):
    """对话响应"""
    data: ChatResult
```

### 3.3 审查模型

```python
# api/schemas/review.py
from pydantic import BaseModel
from typing import Optional, List, Dict
from enum import Enum

class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"

class Violation(BaseModel):
    """违规项"""
    rule_id: str
    rule_name: str
    refdes: str
    net_name: Optional[str] = None
    description: str
    severity: Severity
    expected: Optional[str] = None
    actual: Optional[str] = None
    suggested_fix: Optional[str] = None

class RuleInfo(BaseModel):
    """规则信息"""
    id: str
    name: str
    template_id: str
    severity: Severity
    enabled: bool
    description: Optional[str] = None

class ReviewRequest(BaseModel):
    """审查请求"""
    rule_ids: Optional[List[str]] = None  # None 表示全量审查
    enabled_only: bool = True

class ReviewReport(BaseModel):
    """审查报告"""
    total: int
    errors: int
    warnings: int
    infos: int
    by_rule: Dict[str, int]
    generated_at: str

class ReviewResult(BaseModel):
    """审查结果"""
    violations: List[Violation]
    report_markdown: str
    summary: ReviewReport

class ReviewResponse(BaseResponse):
    """审查响应"""
    data: ReviewResult

class RulesListResponse(BaseResponse):
    """规则列表响应"""
    data: List[RuleInfo]
```

### 3.4 HITL 审批模型

```python
# api/schemas/hitl.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum

class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PERSISTED = "persisted"

class PendingReview(BaseModel):
    """待审批项"""
    review_id: str
    rule_id: str
    rule_name: str
    refdes: str
    net_name: Optional[str] = None
    description: str
    severity: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    suggested_fix: Optional[str] = None
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str
    source: str = "agent"

class PendingListRequest(BaseModel):
    """待审批列表请求"""
    status: Optional[ReviewStatus] = ReviewStatus.PENDING
    page: int = 1
    page_size: int = 50

class PendingListResponse(BaseResponse):
    """待审批列表响应"""
    data: List[PendingReview]
    total: int
    page: int
    page_size: int

class ReviewActionRequest(BaseModel):
    """审批操作请求"""
    review_ids: List[str]
    action: str  # approve, reject
    comment: Optional[str] = None
    reviewer: Optional[str] = "engineer"

class ReviewActionResponse(BaseResponse):
    """审批操作响应"""
    data: Dict[str, bool]  # review_id -> success

class ExportRequest(BaseModel):
    """BOS 导出请求"""
    review_ids: Optional[List[str]] = None  # None 表示导出所有 approved

class ExportResponse(BaseResponse):
    """BOS 导出响应"""
    data: Dict[str, str]  # {"download_url": "...", "expires_at": "..."}
```

### 3.5 知识库模型

```python
# api/schemas/knowledge.py
from pydantic import BaseModel
from typing import Optional, List, Dict
from enum import Enum

class KnowledgeCategory(str, Enum):
    DATASHEET = "datasheet"
    DESIGN_GUIDE = "design_guide"
    APPLICATION_NOTE = "application_note"
    GENERAL = "general"

class UploadRequest(BaseModel):
    """知识上传请求（元数据）"""
    mpn: str
    category: KnowledgeCategory = KnowledgeCategory.GENERAL
    source: Optional[str] = None

class UploadResponse(BaseResponse):
    """知识上传响应"""
    data: Dict[str, any]  # {"chunk_count": 5, "mpn": "..."}

class SearchRequest(BaseModel):
    """知识检索请求"""
    mpn: Optional[str] = None
    query: str
    max_results: int = 5

class SearchResult(BaseModel):
    """检索结果"""
    status: str  # success, not_found, error
    tier: str  # Tier0, Tier1, Tier2, Tier3, none
    content: str
    source: str
    confidence: float
    mpn: Optional[str] = None
    cached: bool = False

class SearchResponse(BaseResponse):
    """检索响应"""
    data: SearchResult

class KnowledgeStats(BaseModel):
    """知识库统计"""
    tier1_chunks: int
    tier2_enabled: bool
    tier3_enabled: bool
    source_distribution: Dict[str, int]

class KnowledgeStatsResponse(BaseResponse):
    """统计响应"""
    data: KnowledgeStats
```

### 3.6 ETL 模型

```python
# api/schemas/etl.py
from pydantic import BaseModel
from typing import Optional, List, Dict
from enum import Enum

class ETLStep(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    VALIDATING = "validating"
    LOADING = "loading"
    COMPLETED = "completed"
    FAILED = "failed"

class ETLPreviewResult(BaseModel):
    """ETL 预览结果"""
    success: bool
    components_count: int
    topology_count: int
    unique_nets: int
    parttype_coverage: float
    parttype_distribution: Dict[str, int]
    power_nets_count: int
    ground_nets_count: int
    top_nets: List[str]

class ETLPreviewResponse(BaseResponse):
    """预览响应"""
    data: ETLPreviewResult

class ETLProgress(BaseModel):
    """ETL 进度"""
    step: ETLStep
    progress: float  # 0-100
    message: str

class QualityReport(BaseModel):
    """质量报告"""
    components: int
    pins: int
    nets: int
    part_type_coverage: float
    passed: bool
    details: Optional[Dict] = None

class ETLResult(BaseModel):
    """ETL 结果"""
    success: bool
    components_count: int
    topology_count: int
    parttype_coverage: float
    quality_passed: bool
    message: str
    quality_report: Optional[QualityReport] = None

class ETLResponse(BaseResponse):
    """ETL 响应"""
    data: ETLResult

class ProjectListResponse(BaseResponse):
    """项目列表响应"""
    data: List[str]

class ProjectActionRequest(BaseModel):
    """项目操作请求"""
    project_name: str

class ProjectActionResponse(BaseResponse):
    """项目操作响应"""
    data: Dict[str, str]  # {"project_id": "..."}
```

### 3.7 图谱可视化模型

```python
# api/schemas/graph.py
from pydantic import BaseModel
from typing import Optional, List, Dict
from enum import Enum

class VizMode(str, Enum):
    COMPONENT = "component"
    POWER_CHAIN = "power_chain"
    FAULT_TRACE = "fault_trace"
    COMMON_CAUSE = "common_cause"
    POWER_TREE = "power_tree"

class Direction(str, Enum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    BOTH = "both"

class GraphRequest(BaseModel):
    """图谱请求"""
    mode: VizMode
    refdes: Optional[str] = None  # 起始组件
    depth: int = 2
    direction: Direction = Direction.BOTH
    voltage: Optional[str] = None  # 电源树模式用

class GraphResult(BaseModel):
    """图谱结果"""
    dot_content: str  # DOT 格式字符串
    node_count: int
    edge_count: int

class GraphResponse(BaseResponse):
    """图谱响应"""
    data: GraphResult
```

### 3.8 系统状态模型

```python
# api/schemas/system.py
from pydantic import BaseModel
from typing import List, Dict
from enum import Enum

class ServiceStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"

class ServiceInfo(BaseModel):
    """服务信息"""
    name: str
    status: ServiceStatus
    latency_ms: Optional[int] = None
    version: Optional[str] = None
    message: Optional[str] = None

class DataStats(BaseModel):
    """数据统计"""
    components: int
    pins: int
    nets: int
    part_type_coverage: float
    by_parttype: Dict[str, int]

class QueryRecord(BaseModel):
    """查询记录"""
    query: str
    task_type: str
    tool_calls: int
    duration_ms: int
    timestamp: str

class AgentStats(BaseModel):
    """Agent 统计"""
    query_count: int
    token_usage: int
    recent_queries: List[QueryRecord]

class SystemStatus(BaseModel):
    """系统状态"""
    services: List[ServiceInfo]
    data_stats: DataStats
    agent_stats: AgentStats

class SystemStatusResponse(BaseResponse):
    """系统状态响应"""
    data: SystemStatus
```

---

## 4. API 端点

### 4.1 对话 API

#### POST /api/v1/chat

执行对话，返回完整结果（非流式）。

**Request Body:**
```json
{
  "message": "帮我审查 I2C 上拉电阻",
  "task_type": "review",
  "context": null
}
```

**Response Body:**
```json
{
  "success": true,
  "data": {
    "status": "success",
    "task_type": "review",
    "report": "## 审查报告\n\n...",
    "execution_trace": [
      {
        "step_id": 1,
        "thought": "需要查找 I2C 相关器件",
        "action": "get_i2c_devices",
        "action_input": {},
        "observation": "I2C 总线器件:\n  网络: I2C_SDA\n    - U30004 (IC) Pin A4\n  ...",
        "timestamp": "2024-01-15T10:30:00.000Z",
        "duration_ms": 150,
        "is_error": false
      }
    ],
    "tool_call_count": 3,
    "timestamp": "2024-01-15T10:30:05.000Z"
  },
  "timestamp": "2024-01-15T10:30:05.000Z"
}
```

---

### 4.2 审查 API

#### GET /api/v1/review/rules

获取所有可用规则列表。

**Response Body:**
```json
{
  "success": true,
  "data": [
    {
      "id": "I2C_STD_PULLUP",
      "name": "I2C 标准上拉电阻检查",
      "template_id": "pullup",
      "severity": "WARNING",
      "enabled": true,
      "description": "检查 I2C 总线 SDA/SCL 是否有上拉电阻"
    },
    {
      "id": "POWER_3V3_DECAP",
      "name": "3.3V 电源去耦电容检查",
      "template_id": "decap",
      "severity": "ERROR",
      "enabled": true,
      "description": "检查 3.3V 电源网络是否有去耦电容"
    }
  ],
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### POST /api/v1/review/run

执行审查。

**Request Body:**
```json
{
  "rule_ids": ["I2C_STD_PULLUP", "POWER_3V3_DECAP"],
  "enabled_only": true
}
```

**Response Body:**
```json
{
  "success": true,
  "data": {
    "violations": [
      {
        "rule_id": "I2C_STD_PULLUP",
        "rule_name": "I2C 标准上拉电阻检查",
        "refdes": "U30004",
        "net_name": "I2C_SDA",
        "description": "I2C_SDA 网络缺少上拉电阻",
        "severity": "WARNING",
        "expected": "上拉电阻 2.2K-10K",
        "actual": "无上拉电阻",
        "suggested_fix": "在 I2C_SDA 网络添加 4.7K 上拉电阻"
      }
    ],
    "report_markdown": "# 原理图审查报告\n\n...",
    "summary": {
      "total": 5,
      "errors": 1,
      "warnings": 3,
      "infos": 1,
      "by_rule": {
        "I2C_STD_PULLUP": 2,
        "POWER_3V3_DECAP": 3
      },
      "generated_at": "2024-01-15T10:30:00.000Z"
    }
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

---

### 4.3 HITL 审批 API

#### GET /api/v1/hitl/pending

获取待审批列表。

**Query Parameters:**
- `status` (string, optional): `pending` | `approved` | `rejected` | `all`
- `page` (int, optional): 页码，默认 1
- `page_size` (int, optional): 每页数量，默认 50

**Response Body:**
```json
{
  "success": true,
  "data": [
    {
      "review_id": "REV_20240115_103000_0001",
      "rule_id": "I2C_STD_PULLUP",
      "rule_name": "I2C 标准上拉电阻检查",
      "refdes": "U30004",
      "net_name": "I2C_SDA",
      "description": "I2C_SDA 网络缺少上拉电阻",
      "severity": "WARNING",
      "expected": "上拉电阻 2.2K-10K",
      "actual": "无上拉电阻",
      "suggested_fix": "在 I2C_SDA 网络添加 4.7K 上拉电阻",
      "status": "pending",
      "reviewer": null,
      "review_comment": null,
      "reviewed_at": null,
      "created_at": "2024-01-15T10:30:00.000Z",
      "source": "agent"
    }
  ],
  "total": 10,
  "page": 1,
  "page_size": 50,
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### POST /api/v1/hitl/action

执行审批操作（支持批量）。

**Request Body:**
```json
{
  "review_ids": ["REV_20240115_103000_0001", "REV_20240115_103000_0002"],
  "action": "approve",
  "comment": "确认问题，需要修复",
  "reviewer": "zhang_san"
}
```

**Response Body:**
```json
{
  "success": true,
  "data": {
    "REV_20240115_103000_0001": true,
    "REV_20240115_103000_0002": true
  },
  "message": "已审批 2 条记录",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### POST /api/v1/hitl/export

导出已审批规则到 BOS。

**Request Body:**
```json
{
  "review_ids": null
}
```

**Response Body:**
```json
{
  "success": true,
  "data": {
    "download_url": "https://bos.example.com/download/xxx?signature=yyy",
    "expires_at": "2024-01-15T11:30:00.000Z",
    "file_name": "approved_rules_20240115.json",
    "rule_count": 5
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

---

### 4.4 知识库 API

#### POST /api/v1/knowledge/upload

上传知识文档。使用 `multipart/form-data`。

**Request:**
- `file`: 文件（PDF/TXT）
- `mpn`: 器件型号
- `category`: 分类 (`datasheet` | `design_guide` | `general`)
- `source`: 来源描述

**Response Body:**
```json
{
  "success": true,
  "data": {
    "chunk_count": 15,
    "mpn": "MT25QU256ABA8E12",
    "file_name": "MT25QU256_datasheet.pdf",
    "indexed_at": "2024-01-15T10:30:00.000Z"
  },
  "message": "成功导入 15 个知识切片",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### POST /api/v1/knowledge/search

知识检索测试。

**Request Body:**
```json
{
  "mpn": "MT25QU256ABA8E12",
  "query": "pinout voltage specifications",
  "max_results": 5
}
```

**Response Body:**
```json
{
  "success": true,
  "data": {
    "status": "success",
    "tier": "Tier1",
    "content": "MT25QU256 Flash Memory\nMPN: MT25QU256ABA8E12\nPackage: TPBGA24\nVoltage: 1.8V SPI Interface\n...",
    "source": "local:datasheet",
    "confidence": 0.85,
    "mpn": "MT25QU256ABA8E12",
    "cached": true
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### GET /api/v1/knowledge/stats

获取知识库统计。

**Response Body:**
```json
{
  "success": true,
  "data": {
    "tier1_chunks": 1520,
    "tier2_enabled": true,
    "tier3_enabled": false,
    "source_distribution": {
      "datasheet": 800,
      "design_guide": 450,
      "application_note": 270
    }
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

---

### 4.5 ETL 导入 API

#### GET /api/v1/etl/projects

获取项目列表。

**Response Body:**
```json
{
  "success": true,
  "data": ["default", "project_alpha", "project_beta"],
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### POST /api/v1/etl/projects

创建新项目。

**Request Body:**
```json
{
  "project_name": "project_gamma"
}
```

**Response Body:**
```json
{
  "success": true,
  "data": {
    "project_id": "project_gamma",
    "created_at": "2024-01-15T10:30:00.000Z"
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### DELETE /api/v1/etl/projects/{project_name}

删除项目。

**Response Body:**
```json
{
  "success": true,
  "message": "项目 project_gamma 已删除",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### POST /api/v1/etl/preview

预览 ETL 导入数据。使用 `multipart/form-data`。

**Request:**
- `pstxnet`: 网表文件
- `pstxprt`: 器件文件
- `pstchip`: 芯片库文件
- `bom`: BOM 文件（可选）

**Response Body:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "components_count": 1250,
    "topology_count": 8500,
    "unique_nets": 320,
    "parttype_coverage": 92.5,
    "parttype_distribution": {
      "CAPACITOR": 450,
      "RESISTOR": 380,
      "IC": 120,
      "CONNECTOR": 45
    },
    "power_nets_count": 15,
    "ground_nets_count": 3,
    "top_nets": ["GND", "VCC_3V3", "VCC_1V8", "I2C_SDA", "I2C_SCL"]
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### POST /api/v1/etl/run

执行 ETL 导入。使用 `multipart/form-data`。

**Request:**
- `pstxnet`: 网表文件
- `pstxprt`: 器件文件
- `pstchip`: 芯片库文件
- `bom`: BOM 文件（可选）
- `project_name`: 项目名称

**Response Body:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "components_count": 1250,
    "topology_count": 8500,
    "parttype_coverage": 92.5,
    "quality_passed": true,
    "message": "ETL 完成",
    "quality_report": {
      "components": 1250,
      "pins": 6800,
      "nets": 320,
      "part_type_coverage": 92.5,
      "passed": true
    }
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### GET /api/v1/etl/progress/{job_id}

查询 ETL 进度。

**Response Body:**
```json
{
  "success": true,
  "data": {
    "step": "loading",
    "progress": 75.5,
    "message": "正在加载拓扑数据到 Neo4j..."
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

---

### 4.6 图谱可视化 API

#### POST /api/v1/graph/visualize

生成图谱可视化 DOT。

**Request Body:**
```json
{
  "mode": "component",
  "refdes": "U30004",
  "depth": 2,
  "direction": "both",
  "voltage": null
}
```

**Response Body:**
```json
{
  "success": true,
  "data": {
    "dot_content": "graph G {\n  rankdir=LR;\n  node [fontname=\"Arial\"];\n  ...\n}",
    "node_count": 25,
    "edge_count": 40
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

**Mode 说明：**

| mode | 说明 | 必填参数 |
|------|------|----------|
| `component` | 组件关系图 | `refdes`, `depth` |
| `power_chain` | 电源链路 | `refdes`, `direction`, `depth` |
| `fault_trace` | 故障溯源 | `refdes` |
| `common_cause` | 共因失效 | `refdes`（多个用逗号分隔） |
| `power_tree` | 电源树 | `refdes` 或 `voltage` |

---

### 4.7 系统状态 API

#### GET /api/v1/system/status

获取系统状态。

**Response Body:**
```json
{
  "success": true,
  "data": {
    "services": [
      {
        "name": "Neo4j",
        "status": "running",
        "latency_ms": 5,
        "version": "5.12.0"
      },
      {
        "name": "Ollama",
        "status": "running",
        "latency_ms": 15,
        "version": "0.1.26"
      },
      {
        "name": "ChromaDB",
        "status": "running",
        "latency_ms": 8
      },
      {
        "name": "API Server",
        "status": "running",
        "version": "1.0.0"
      }
    ],
    "data_stats": {
      "components": 1250,
      "pins": 6800,
      "nets": 320,
      "part_type_coverage": 92.5,
      "by_parttype": {
        "CAPACITOR": 450,
        "RESISTOR": 380,
        "IC": 120
      }
    },
    "agent_stats": {
      "query_count": 156,
      "token_usage": 125000,
      "recent_queries": [
        {
          "query": "审查 I2C 上拉电阻",
          "task_type": "review",
          "tool_calls": 3,
          "duration_ms": 5200,
          "timestamp": "2024-01-15T10:25:00.000Z"
        }
      ]
    }
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

---

## 5. WebSocket API

### 5.1 连接端点

```
ws://localhost:8501/ws/chat
```

### 5.2 消息协议

#### 客户端 → 服务端

**发送对话消息：**
```json
{
  "type": "chat",
  "payload": {
    "message": "帮我审查 I2C 上拉电阻",
    "task_type": "review"
  }
}
```

**心跳：**
```json
{
  "type": "ping"
}
```

#### 服务端 → 客户端

**推理步骤推送：**
```json
{
  "type": "step",
  "payload": {
    "step": {
      "step_id": 1,
      "thought": "需要查找 I2C 相关器件",
      "action": "get_i2c_devices",
      "action_input": {},
      "observation": "I2C 总线器件:\n  网络: I2C_SDA\n    - U30004 (IC) Pin A4",
      "timestamp": "2024-01-15T10:30:00.000Z",
      "duration_ms": 150,
      "is_error": false
    }
  }
}
```

**最终结果：**
```json
{
  "type": "result",
  "payload": {
    "result": {
      "status": "success",
      "task_type": "review",
      "report": "## 审查报告\n\n...",
      "execution_trace": [...],
      "tool_call_count": 3,
      "timestamp": "2024-01-15T10:30:05.000Z"
    }
  }
}
```

**错误：**
```json
{
  "type": "error",
  "payload": {
    "error": "LLM 服务超时"
  }
}
```

**心跳响应：**
```json
{
  "type": "pong"
}
```

---

## 6. 文件上传规范

### 6.1 支持的文件类型

| 端点 | 文件字段 | 文件类型 | 最大大小 |
|------|----------|----------|----------|
| `/api/v1/knowledge/upload` | `file` | PDF, TXT | 50MB |
| `/api/v1/etl/preview` | `pstxnet`, `pstxprt`, `pstchip`, `bom` | TXT, CSV, DAT | 100MB |
| `/api/v1/etl/run` | `pstxnet`, `pstxprt`, `pstchip`, `bom` | TXT, CSV, DAT | 100MB |

### 6.2 上传流程

1. 前端使用 `multipart/form-data` 格式上传
2. 后端校验文件类型和大小
3. 保存到临时目录
4. 处理完成后删除临时文件

---

## 7. CORS 配置

开发环境允许 `localhost` 访问：

```python
# api/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 8. 认证与授权（预留）

### 8.1 JWT Token

```python
# api/auth.py
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    # 验证 JWT
    user = verify_jwt_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user
```

### 8.2 API 调用示例

```bash
curl -X POST http://localhost:8501/api/v1/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我审查 I2C 上拉电阻"}'
```

---

## 9. 错误处理示例

### 9.1 参数校验错误

**请求：**
```bash
curl -X POST http://localhost:8501/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": ""}'
```

**响应：**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_REQUEST",
    "message": "message 字段不能为空",
    "details": {
      "field": "message",
      "constraint": "min_length=1"
    }
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

### 9.2 服务不可用

**请求：**
```bash
curl http://localhost:8501/api/v1/system/status
```

**响应（Neo4j 未连接）：**
```json
{
  "success": false,
  "error": {
    "code": "SERVICE_UNAVAILABLE",
    "message": "Neo4j 数据库连接失败",
    "details": {
      "service": "Neo4j",
      "error": "Connection refused"
    }
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

---

## 10. API 实现映射

| API 端点 | 后端模块 | 核心函数 |
|----------|----------|----------|
| `/api/v1/chat` | `agent_system.react_agent` | `ReActAgent.run()` |
| `/api/v1/review/*` | `agent_system.review_engine` | `ReviewRuleEngine.run_rules()` |
| `/api/v1/hitl/*` | `agent_system.hitl_workflow` | `HITLManager.*` |
| `/api/v1/knowledge/*` | `agent_system.knowledge_router` | `KnowledgeRouter.*` |
| `/api/v1/etl/*` | `agent_system.etl_web_bridge` | `ETLWebExecutor.*` |
| `/api/v1/graph/*` | `web_ui.sub_pages.graph_viz` | `*_build_*_dot()` |
| `/api/v1/system/*` | `agent_system.graph_tools` | `get_graph_summary()` |

---

## 11. OpenAPI 文档

FastAPI 自动生成 OpenAPI 文档：

- Swagger UI: `http://localhost:8501/docs`
- ReDoc: `http://localhost:8501/redoc`
- OpenAPI JSON: `http://localhost:8501/openapi.json`

---

## 附录 A：FastAPI 项目结构

```
/data/schematic_agent/hardware_ai_expert/api/
├── __init__.py
├── main.py              # FastAPI 应用入口
├── config.py            # 配置管理
├── dependencies.py      # 依赖注入
├── routers/
│   ├── __init__.py
│   ├── chat.py          # 对话路由
│   ├── review.py        # 审查路由
│   ├── hitl.py          # HITL 路由
│   ├── knowledge.py     # 知识库路由
│   ├── etl.py           # ETL 路由
│   ├── graph.py         # 图谱路由
│   └── system.py        # 系统路由
├── schemas/
│   ├── __init__.py
│   ├── base.py
│   ├── chat.py
│   ├── review.py
│   ├── hitl.py
│   ├── knowledge.py
│   ├── etl.py
│   ├── graph.py
│   └── system.py
├── services/
│   ├── __init__.py
│   ├── chat_service.py
│   ├── review_service.py
│   └── ...
└── websocket/
    ├── __init__.py
    └── chat_ws.py       # WebSocket 处理
```

---

## 附录 B：启动命令

```bash
# 开发模式
cd /data/schematic_agent/hardware_ai_expert
uvicorn api.main:app --reload --host 0.0.0.0 --port 8501

# 生产模式
uvicorn api.main:app --host 0.0.0.0 --port 8501 --workers 4
```
