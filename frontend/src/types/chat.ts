// Chat types
import type { ApprovalState } from './agent';
export type TaskType = 'review' | 'diagnosis' | 'query' | 'auto';

export interface ReasoningStep {
  step_id: number;
  thought: string;
  action: string;
  action_input: Record<string, unknown>;
  observation: string;
  timestamp: string;
  duration_ms?: number;
  is_error: boolean;
}

export interface ChatRequest {
  message: string;
  task_type?: TaskType;
  context?: Record<string, unknown>;
  project_id?: string;
}

export interface ChatResult {
  status: string;
  task_type: string;
  report: string;
  execution_trace: ReasoningStep[];
  tool_call_count: number;
  timestamp: string;
}

export interface ChatResponse {
  success: boolean;
  data: ChatResult;
  message?: string;
  timestamp: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  reasoningTrace?: ReasoningStep[];
  taskType?: string;
  /** Hermes 引擎：待审批/已审批的写工具调用（一个 run 可能多次触发） */
  approvals?: ApprovalState[];
  /** 运行过程提示（工具调用等），仅 Hermes 引擎使用 */
  progress?: string[];
}
