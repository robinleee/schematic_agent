# 前端架构设计文档

## 1. 概述

本文档描述硬件 AI 专家系统（schematic_agent）前端重构的架构设计方案。目标是将现有 Streamlit 应用（~4400 行）重构为现代化独立前端，采用 React + TypeScript + Ant Design 技术栈。

---

## 2. 技术栈选型

### 2.1 核心技术栈

| 技术 | 版本 | 选型理由 |
|------|------|----------|
| **React** | 18.x | 主流前端框架，生态成熟，组件化开发 |
| **TypeScript** | 5.x | 类型安全，IDE 支持好，大型项目必备 |
| **Ant Design** | 5.x | 中文友好，企业级 UI 组件库，开箱即用 |
| **Vite** | 5.x | 极速构建，HMR 快，开发体验好 |
| **React Router** | 6.x | 标准路由方案，支持懒加载 |
| **Zustand** | 4.x | 轻量状态管理，比 Redux 简洁 |
| **React Query** | 5.x | 服务端状态管理，自动缓存、重试 |
| **D3.js** | 7.x | 图谱可视化，灵活强大 |
| **Axios** | 1.x | HTTP 客户端，拦截器支持 |

### 2.2 开发工具

- **ESLint** + **Prettier** — 代码规范与格式化
- **Vitest** — 单元测试
- **Playwright** — E2E 测试（可选）

---

## 3. 项目结构

```
/data/schematic_agent/frontend/
├── public/                     # 静态资源
│   └── favicon.ico
├── src/
│   ├── main.tsx               # 入口文件
│   ├── App.tsx                # 根组件
│   ├── vite-env.d.ts          # Vite 类型声明
│   │
│   ├── api/                   # API 层
│   │   ├── client.ts          # Axios 实例配置
│   │   ├── chat.ts            # 对话相关 API
│   │   ├── review.ts          # 审查相关 API
│   │   ├── hitl.ts            # HITL 审批 API
│   │   ├── knowledge.ts       # 知识库 API
│   │   ├── etl.ts             # ETL 导入 API
│   │   ├── graph.ts           # 图谱可视化 API
│   │   └── system.ts          # 系统状态 API
│   │
│   ├── components/            # 通用组件
│   │   ├── Layout/
│   │   │   ├── AppLayout.tsx      # 主布局（侧边栏+内容区）
│   │   │   ├── Sidebar.tsx        # 侧边导航栏
│   │   │   └── Header.tsx         # 顶部栏（主题切换等）
│   │   ├── Chat/
│   │   │   ├── ChatContainer.tsx  # 对话容器
│   │   │   ├── MessageList.tsx    # 消息列表
│   │   │   ├── MessageItem.tsx    # 单条消息
│   │   │   ├── ReasoningChain.tsx # 推理链路展示
│   │   │   ├── ReasoningStep.tsx  # 单步推理
│   │   │   └── ChatInput.tsx      # 输入框
│   │   ├── Review/
│   │   │   ├── ReviewReport.tsx   # 审查报告
│   │   │   ├── ViolationTable.tsx # 违规表格
│   │   │   └── ViolationDetail.tsx# 违规详情
│   │   ├── HITL/
│   │   │   ├── PendingList.tsx    # 待审批列表
│   │   │   ├── ReviewAction.tsx   # 审批操作面板
│   │   │   └── BatchAction.tsx    # 批量操作
│   │   ├── Knowledge/
│   │   │   ├── FileUpload.tsx     # 文件上传
│   │   │   ├── SearchTest.tsx     # 知识检索测试
│   │   │   └── KnowledgeStats.tsx # 知识库统计
│   │   ├── ETL/
│   │   │   ├── FileUploader.tsx   # 文件上传器
│   │   │   ├── PreviewTable.tsx   # 预览表格
│   │   │   ├── ImportProgress.tsx # 导入进度
│   │   │   └── QualityReport.tsx  # 质量报告
│   │   ├── Graph/
│   │   │   ├── GraphCanvas.tsx    # 图谱画布
│   │   │   ├── GraphControls.tsx  # 控制面板
│   │   │   └── GraphLegend.tsx    # 图例
│   │   └── System/
│   │       ├── ServiceStatus.tsx  # 服务状态卡片
│   │       └── DataStats.tsx      # 数据统计
│   │
│   ├── pages/                  # 页面组件
│   │   ├── Chat/
│   │   │   └── index.tsx       # 智能对话页
│   │   ├── Review/
│   │   │   └── index.tsx       # 原理图审查页
│   │   ├── HITL/
│   │   │   └── index.tsx       # HITL 审批页
│   │   ├── Knowledge/
│   │   │   └── index.tsx       # 知识库管理页
│   │   ├── ETL/
│   │   │   └── index.tsx       # ETL 导入页
│   │   ├── Graph/
│   │   │   └── index.tsx       # 图谱可视化页
│   │   └── System/
│   │       └── index.tsx       # 系统状态页
│   │
│   ├── stores/                 # Zustand 状态仓库
│   │   ├── useChatStore.ts     # 对话状态
│   │   ├── useThemeStore.ts    # 主题状态
│   │   └── useProjectStore.ts  # 项目状态
│   │
│   ├── hooks/                  # 自定义 Hooks
│   │   ├── useWebSocket.ts     # WebSocket 连接
│   │   ├── useTheme.ts         # 主题切换
│   │   └── useDebounce.ts      # 防抖
│   │
│   ├── types/                  # TypeScript 类型定义
│   │   ├── chat.ts
│   │   ├── review.ts
│   │   ├── hitl.ts
│   │   ├── knowledge.ts
│   │   ├── etl.ts
│   │   ├── graph.ts
│   │   └── system.ts
│   │
│   ├── utils/                  # 工具函数
│   │   ├── request.ts          # 请求封装
│   │   ├── format.ts           # 格式化
│   │   └── storage.ts          # 本地存储
│   │
│   └── styles/                 # 样式文件
│       ├── variables.css       # CSS 变量
│       ├── global.css          # 全局样式
│       └── themes/
│           ├── light.css       # 亮色主题
│           └── dark.css        # 暗色主题
│
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── .env.development            # 环境变量
```

---

## 4. 页面路由设计

### 4.1 路由表

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | 重定向到 `/chat` | 默认页 |
| `/chat` | Chat | 智能对话 |
| `/review` | Review | 原理图审查 |
| `/hitl` | HITL | HITL 审批面板 |
| `/knowledge` | Knowledge | 知识库管理 |
| `/etl` | ETL | ETL 导入 |
| `/graph` | Graph | 图谱可视化 |
| `/system` | System | 系统状态 |

### 4.2 路由配置

```typescript
// src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { Spin } from 'antd';
import AppLayout from '@/components/Layout/AppLayout';

// 懒加载页面
const Chat = lazy(() => import('@/pages/Chat'));
const Review = lazy(() => import('@/pages/Review'));
const HITL = lazy(() => import('@/pages/HITL'));
const Knowledge = lazy(() => import('@/pages/Knowledge'));
const ETL = lazy(() => import('@/pages/ETL'));
const Graph = lazy(() => import('@/pages/Graph'));
const System = lazy(() => import('@/pages/System'));

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Spin size="large" />}>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route index element={<Navigate to="/chat" replace />} />
            <Route path="chat" element={<Chat />} />
            <Route path="review" element={<Review />} />
            <Route path="hitl" element={<HITL />} />
            <Route path="knowledge" element={<Knowledge />} />
            <Route path="etl" element={<ETL />} />
            <Route path="graph" element={<Graph />} />
            <Route path="system" element={<System />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
```

---

## 5. 组件设计

### 5.1 智能对话页面 (Chat)

**组件树：**

```
Chat (pages/Chat/index.tsx)
├── ChatContainer (components/Chat/ChatContainer.tsx)
│   ├── Header
│   │   ├── 清空对话按钮
│   │   └── 系统概览按钮
│   ├── MessageList (components/Chat/MessageList.tsx)
│   │   └── MessageItem (components/Chat/MessageItem.tsx) × N
│   │       ├── Avatar (用户/AI)
│   │       ├── MessageContent (Markdown 渲染)
│   │       └── ReasoningChain (components/Chat/ReasoningChain.tsx)
│   │           └── ReasoningStep (components/Chat/ReasoningStep.tsx) × N
│   │               ├── StepIcon (思考/执行/观察/结论)
│   │               ├── ThoughtText
│   │               ├── ActionBadge
│   │               ├── ObservationText
│   │               └── Duration
│   └── ChatInput (components/Chat/ChatInput.tsx)
│       ├── TextArea
│       └── SendButton
└── QuickActions (快捷操作面板)
    ├── 审查按钮
    ├── 诊断按钮
    └── 查询按钮
```

**核心 Props/State：**

```typescript
// components/Chat/ChatContainer.tsx
interface ChatContainerProps {
  // 无 props，内部管理状态
}

interface ChatState {
  messages: Message[];
  isLoading: boolean;
  currentTaskType: 'review' | 'diagnosis' | 'query' | null;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  reasoningTrace?: ReasoningStep[];
  taskType?: string;
}

interface ReasoningStep {
  stepId: number;
  thought: string;
  action: string;
  actionInput: Record<string, any>;
  observation: string;
  timestamp: string;
  duration?: number;
  isError?: boolean;
}
```

### 5.2 原理图审查页面 (Review)

**组件树：**

```
Review (pages/Review/index.tsx)
├── ReviewControls
│   ├── RuleSelector (Ant Design Select)
│   ├── RunButton
│   └── FullReviewSwitch
├── ReviewReport (components/Review/ReviewReport.tsx)
│   ├── SummaryCards
│   │   ├── TotalCount
│   │   ├── ErrorCount
│   │   ├── WarningCount
│   │   └── InfoCount
│   └── ViolationTable (components/Review/ViolationTable.tsx)
│       └── ViolationRow × N
│           ├── SeverityBadge (颜色编码)
│           ├── RuleId
│           ├── RefDes
│           ├── Description
│           └── ExpandButton
│               └── ViolationDetail (components/Review/ViolationDetail.tsx)
│                   ├── NetName
│                   ├── Expected
│                   ├── Actual
│                   └── SuggestedFix
```

**核心 Props/State：**

```typescript
interface ReviewProps {}

interface ReviewState {
  selectedRules: string[];
  isRunning: boolean;
  violations: Violation[];
  report: ReviewReport | null;
}

interface Violation {
  ruleId: string;
  ruleName: string;
  refdes: string;
  netName: string;
  description: string;
  severity: 'ERROR' | 'WARNING' | 'INFO';
  expected: string;
  actual: string;
  suggestedFix?: string;
}

interface ReviewReport {
  total: number;
  errors: number;
  warnings: number;
  infos: number;
  byRule: Record<string, number>;
  generatedAt: string;
}
```

### 5.3 HITL 审批页面 (HITL)

**组件树：**

```
HITL (pages/HITL/index.tsx)
├── HITLHeader
│   ├── StatusFilter (pending/approved/rejected)
│   ├── RefreshButton
│   └── ExportButton (BOS 导出)
├── PendingList (components/HITL/PendingList.tsx)
│   └── PendingItem × N
│       ├── SeverityBadge
│       ├── RuleInfo
│       ├── ComponentInfo
│       ├── Description
│       ├── StatusTag
│       └── ReviewAction (components/HITL/ReviewAction.tsx)
│           ├── ApproveButton
│           ├── RejectButton
│           └── CommentInput
├── BatchAction (components/HITL/BatchAction.tsx)
│   ├── SelectAll
│   ├── BatchApprove
│   └── BatchReject
└── StatsPanel
    ├── PendingCount
    ├── ApprovedCount
    └── RejectedCount
```

**核心 Props/State：**

```typescript
interface HITLProps {}

interface HITLState {
  filterStatus: 'pending' | 'approved' | 'rejected' | 'all';
  selectedIds: string[];
  pendingReviews: PendingReview[];
  isLoading: boolean;
}

interface PendingReview {
  reviewId: string;
  ruleId: string;
  ruleName: string;
  refdes: string;
  netName: string;
  description: string;
  severity: string;
  expected: string;
  actual: string;
  status: 'pending' | 'approved' | 'rejected';
  reviewer?: string;
  reviewComment?: string;
  reviewedAt?: string;
  createdAt: string;
}
```

### 5.4 知识库管理页面 (Knowledge)

**组件树：**

```
Knowledge (pages/Knowledge/index.tsx)
├── Tabs (Ant Design Tabs)
│   ├── Tab: 文档上传
│   │   ├── FileUpload (components/Knowledge/FileUpload.tsx)
│   │   │   ├── Dragger (PDF/文本)
│   │   │   ├── MPNInput
│   │   │   ├── CategorySelect
│   │   │   └── UploadButton
│   │   └── UploadHistory
│   │       └── UploadItem × N
│   ├── Tab: 知识检索测试
│   │   ├── SearchTest (components/Knowledge/SearchTest.tsx)
│   │   │   ├── MPNInput
│   │   │   ├── QueryInput
│   │   │   └── SearchButton
│   │   └── SearchResult
│   │       ├── TierBadge (Tier0/1/2/3)
│   │       ├── ConfidenceScore
│   │       └── ContentPreview
│   └── Tab: 知识库统计
│       └── KnowledgeStats (components/Knowledge/KnowledgeStats.tsx)
│           ├── ChunksCount
│           ├── SourceDistribution (饼图)
│           └── RecentActivity
```

**核心 Props/State：**

```typescript
interface KnowledgeProps {}

interface KnowledgeState {
  activeTab: 'upload' | 'search' | 'stats';
  uploadFiles: File[];
  searchQuery: {
    mpn: string;
    query: string;
  };
  searchResults: SearchResult[];
  stats: KnowledgeStats;
}

interface SearchResult {
  status: string;
  tier: string;
  content: string;
  source: string;
  confidence: number;
  mpn: string;
}

interface KnowledgeStats {
  tier1Chunks: number;
  tier2Enabled: boolean;
  tier3Enabled: boolean;
  sourceDistribution: Record<string, number>;
}
```

### 5.5 ETL 导入页面 (ETL)

**组件树：**

```
ETL (pages/ETL/index.tsx)
├── ProjectSelector
│   ├── CurrentProject
│   ├── CreateProjectButton
│   └── DeleteProjectButton
├── FileUploader (components/ETL/FileUploader.tsx)
│   ├── Dragger × 4
│   │   ├── pstxnet (.txt)
│   │   ├── pstxprt (.txt)
│   │   ├── pstchip (.txt)
│   │   └── bom (.csv, 可选)
│   └── PreviewButton
├── PreviewTable (components/ETL/PreviewTable.tsx)
│   ├── ComponentsPreview
│   │   └── Ant Design Table
│   ├── TopologyPreview
│   │   └── Ant Design Table
│   └── StatsSummary
├── ImportProgress (components/ETL/ImportProgress.tsx)
│   ├── Steps (Ant Design Steps)
│   ├── CurrentStep
│   └── ProgressBar
└── QualityReport (components/ETL/QualityReport.tsx)
    ├── PartTypeCoverage
    ├── ComponentsCount
    ├── PinsCount
    └── NetsCount
```

**核心 Props/State：**

```typescript
interface ETLProps {}

interface ETLState {
  currentProject: string;
  projects: string[];
  files: {
    pstxnet: File | null;
    pstxprt: File | null;
    pstchip: File | null;
    bom: File | null;
  };
  preview: ETLPreview | null;
  importProgress: ImportProgress | null;
  qualityReport: QualityReport | null;
}

interface ETLPreview {
  componentsCount: number;
  topologyCount: number;
  uniqueNets: number;
  parttypeCoverage: number;
  parttypeDistribution: Record<string, number>;
}

interface ImportProgress {
  step: 'parsing' | 'validating' | 'loading' | 'completed' | 'failed';
  progress: number;
  message: string;
}

interface QualityReport {
  components: number;
  pins: number;
  nets: number;
  partTypeCoverage: number;
  passed: boolean;
}
```

### 5.6 图谱可视化页面 (Graph)

**组件树：**

```
Graph (pages/Graph/index.tsx)
├── GraphControls (components/Graph/GraphControls.tsx)
│   ├── VizModeSelect (5种模式)
│   │   ├── 组件关系
│   │   ├── 电源链路
│   │   ├── 故障溯源
│   │   ├── 共因失效
│   │   └── 电源树
│   ├── RefDesInput (起始组件)
│   ├── DepthSlider (深度控制)
│   ├── DirectionSelect (upstream/downstream/both)
│   └── RenderButton
├── GraphCanvas (components/Graph/GraphCanvas.tsx)
│   ├── D3.js SVG
│   ├── Nodes
│   │   ├── ComponentNode (矩形蓝色)
│   │   └── NetNode (圆形灰色/红色)
│   └── Edges
└── GraphLegend (components/Graph/GraphLegend.tsx)
    ├── ComponentLegend
    ├── PowerNetLegend
    └── SignalNetLegend
```

**核心 Props/State：**

```typescript
interface GraphProps {}

interface GraphState {
  vizMode: 'component' | 'power_chain' | 'fault_trace' | 'common_cause' | 'power_tree';
  refdes: string;
  depth: number;
  direction: 'upstream' | 'downstream' | 'both';
  dotContent: string | null;
  isLoading: boolean;
}
```

### 5.7 系统状态页面 (System)

**组件树：**

```
System (pages/System/index.tsx)
├── ServiceStatus (components/System/ServiceStatus.tsx)
│   └── StatusCard × 4
│       ├── Neo4j
│       ├── Ollama
│       ├── ChromaDB
│       └── API Server
├── DataStats (components/System/DataStats.tsx)
│   ├── ComponentsCount
│   ├── PinsCount
│   ├── NetsCount
│   └── PartTypeCoverage (进度条)
└── AgentStats
    ├── QueryCount
    ├── TokenUsage
    └── RecentQueries (表格)
```

**核心 Props/State：**

```typescript
interface SystemProps {}

interface SystemState {
  services: ServiceStatus[];
  dataStats: DataStats;
  agentStats: AgentStats;
}

interface ServiceStatus {
  name: string;
  status: 'running' | 'stopped' | 'error';
  latency?: number;
  version?: string;
}

interface DataStats {
  components: number;
  pins: number;
  nets: number;
  partTypeCoverage: number;
}

interface AgentStats {
  queryCount: number;
  tokenUsage: number;
  recentQueries: QueryRecord[];
}
```

---

## 6. 状态管理方案

### 6.1 状态分层

| 状态类型 | 管理方案 | 示例 |
|----------|----------|------|
| **服务端状态** | React Query | 对话历史、审查结果、待审批列表 |
| **全局客户端状态** | Zustand | 主题、当前项目 |
| **局部状态** | useState | 表单输入、UI 开关 |

### 6.2 Zustand Store 示例

```typescript
// src/stores/useThemeStore.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ThemeState {
  theme: 'light' | 'dark';
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'light',
      toggleTheme: () =>
        set((state) => ({
          theme: state.theme === 'light' ? 'dark' : 'light',
        })),
    }),
    { name: 'theme-storage' }
  )
);
```

```typescript
// src/stores/useProjectStore.ts
import { create } from 'zustand';

interface ProjectState {
  currentProject: string;
  projects: string[];
  setCurrentProject: (project: string) => void;
  setProjects: (projects: string[]) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  currentProject: 'default',
  projects: ['default'],
  setCurrentProject: (project) => set({ currentProject: project }),
  setProjects: (projects) => set({ projects }),
}));
```

---

## 7. 主题方案

### 7.1 CSS 变量体系

```css
/* src/styles/themes/light.css */
:root[data-theme='light'] {
  --bg-primary: #ffffff;
  --bg-secondary: #f5f5f5;
  --bg-card: #ffffff;
  --border-color: #e0e0e0;
  --text-primary: #1f1f1f;
  --text-secondary: #666666;
  --accent-primary: #1890ff;
  --accent-success: #52c41a;
  --accent-warning: #faad14;
  --accent-error: #ff4d4f;
}

/* src/styles/themes/dark.css */
:root[data-theme='dark'] {
  --bg-primary: #141414;
  --bg-secondary: #1f1f1f;
  --bg-card: #262626;
  --border-color: #434343;
  --text-primary: #ffffff;
  --text-secondary: #a6a6a6;
  --accent-primary: #177ddc;
  --accent-success: #49aa19;
  --accent-warning: #d89614;
  --accent-error: #d32029;
}
```

### 7.2 Ant Design 主题定制

```typescript
// src/main.tsx
import { ConfigProvider, theme } from 'antd';
import { useThemeStore } from '@/stores/useThemeStore';

const antdTheme = {
  light: {
    token: {
      colorPrimary: '#1890ff',
      borderRadius: 6,
    },
  },
  dark: {
    algorithm: theme.darkAlgorithm,
    token: {
      colorPrimary: '#177ddc',
      borderRadius: 6,
    },
  },
};

function App() {
  const { theme } = useThemeStore();
  return (
    <ConfigProvider theme={antdTheme[theme]}>
      {/* ... */}
    </ConfigProvider>
  );
}
```

---

## 8. 响应式断点

采用 Ant Design 默认断点：

| 断点 | 宽度 | 说明 |
|------|------|------|
| xs | < 576px | 手机 |
| sm | ≥ 576px | 小平板 |
| md | ≥ 768px | 平板 |
| lg | ≥ 992px | 桌面 |
| xl | ≥ 1200px | 大屏 |
| xxl | ≥ 1600px | 超大屏 |

**主要适配策略：**

- 侧边栏在 `md` 以下自动收起
- 表格在 `sm` 以下改为卡片列表
- 图谱画布保持全宽，控制面板折叠

---

## 9. WebSocket 协议（对话流式）

### 9.1 连接建立

```typescript
// 客户端
const ws = new WebSocket('ws://localhost:8501/ws/chat');

// 连接成功后发送消息
ws.send(JSON.stringify({
  type: 'chat',
  payload: {
    message: '帮我审查 I2C 上拉电阻',
    taskType: 'review',  // 可选
  }
}));
```

### 9.2 消息格式

**请求：**

```typescript
interface WSRequest {
  type: 'chat' | 'ping';
  payload?: {
    message: string;
    taskType?: 'review' | 'diagnosis' | 'query';
  };
}
```

**响应：**

```typescript
interface WSResponse {
  type: 'step' | 'result' | 'error' | 'pong';
  payload: {
    step?: ReasoningStep;    // 推理步骤
    result?: ChatResult;     // 最终结果
    error?: string;          // 错误信息
  };
}

interface ChatResult {
  status: 'success' | 'timeout' | 'error';
  taskType: string;
  report: string;            // Markdown 报告
  executionTrace: ReasoningStep[];
  toolCallCount: number;
  timestamp: string;
}
```

### 9.3 使用示例

```typescript
// src/hooks/useWebSocket.ts
import { useState, useCallback } from 'react';

export function useChatWebSocket() {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  const connect = useCallback(() => {
    const ws = new WebSocket('ws://localhost:8501/ws/chat');

    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => setIsConnected(false);

    setSocket(ws);
  }, []);

  const send = useCallback((message: string, taskType?: string) => {
    if (socket && isConnected) {
      socket.send(JSON.stringify({
        type: 'chat',
        payload: { message, taskType },
      }));
    }
  }, [socket, isConnected]);

  return { connect, send, isConnected };
}
```

---

## 10. 构建与部署

### 10.1 开发命令

```bash
# 安装依赖
npm install

# 开发模式
npm run dev

# 构建生产版本
npm run build

# 预览生产版本
npm run preview
```

### 10.2 Vite 配置

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8501',
      '/ws': {
        target: 'ws://localhost:8501',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
```

### 10.3 部署架构

```
┌─────────────────────────────────────────┐
│          FastAPI Server (8501)          │
├─────────────────────────────────────────┤
│  /api/*  ──→  REST API 端点             │
│  /ws/*   ──→  WebSocket 端点            │
│  /*      ──→  静态文件 (frontend/dist)  │
└─────────────────────────────────────────┘
```

FastAPI 同时服务 API 和前端静态文件，实现单端口部署。

---

## 11. 性能优化

### 11.1 代码分割

- 页面级懒加载（React.lazy）
- 大型组件（图谱）独立 chunk
- 第三方库（D3.js）按需加载

### 11.2 缓存策略

- React Query 缓存服务端数据
- 静态资源 CDN + 长期缓存
- IndexedDB 存储大文件预览

### 11.3 图谱优化

- 节点数量限制（>500 节点启用聚合）
- SVG 虚拟滚动
- Canvas 模式降级

---

## 12. 安全考虑

- JWT Token 认证（预留）
- XSS 防护（DOMPurify 清洗 Markdown）
- CSRF Token（FastAPI 内置）
- 文件上传类型校验
- API 请求频率限制

---

## 附录 A：目录创建命令

```bash
mkdir -p /data/schematic_agent/frontend/src/{api,components/{Chat,Review,HITL,Knowledge,ETL,Graph,System,Layout},pages/{Chat,Review,HITL,Knowledge,ETL,Graph,System},stores,hooks,types,utils,styles/themes}
```
