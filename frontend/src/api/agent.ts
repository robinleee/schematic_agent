// Hermes agent run API（HTTP + SSE）
import apiClient from './client';
import type {
  AgentHealth,
  AgentRunCreateResponse,
  AgentRunEvent,
  AgentRunState,
  ApprovalChoice,
} from '@/types/agent';

export interface CreateRunParams {
  input: string;
  sessionId?: string;
  projectId?: string;
  model?: string;
}

interface StreamHandlers {
  onEvent: (event: AgentRunEvent) => void;
  /** SSE 的 id: 行（seq），用于断线/刷新后续流去重 */
  onId?: (seq: number) => void;
  signal?: AbortSignal;
}

const BASE = `${import.meta.env.VITE_API_URL || ''}/api/v1/agent`;

/** 把 SSE 文本流切成事件（event: / data: / 空行分隔，忽略 `: comment`） */
function createSseParser(
  onEvent: (event: AgentRunEvent) => void,
  onId?: (seq: number) => void,
) {
  let buffer = '';
  let eventName = 'message';
  const dataLines: string[] = [];

  const flush = () => {
    if (!dataLines.length) return;
    const raw = dataLines.join('\n');
    dataLines.length = 0;
    try {
      const parsed = JSON.parse(raw) as AgentRunEvent;
      onEvent({ ...parsed, event: parsed.event || eventName });
    } catch {
      onEvent({ event: eventName, delta: raw });
    }
    eventName = 'message';
  };

  return (chunk: string) => {
    buffer += chunk;
    let index = buffer.indexOf('\n');
    while (index >= 0) {
      const line = buffer.slice(0, index).replace(/\r$/, '');
      buffer = buffer.slice(index + 1);
      if (line === '') {
        flush();
      } else if (line.startsWith(':')) {
        // keep-alive comment
      } else if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart());
      } else if (line.startsWith('id:')) {
        const seq = Number(line.slice(3).trim());
        if (Number.isFinite(seq) && onId) onId(seq);
      }
      index = buffer.indexOf('\n');
    }
  };
}

export const agentApi = {
  /** 灰度开关 + 网关可达性 */
  health: async (): Promise<AgentHealth> => {
    const response = await apiClient.get<AgentHealth>('/agent/health', { timeout: 8000 });
    return response.data;
  },
  createRun: async (params: CreateRunParams): Promise<AgentRunCreateResponse> => {
    const body: Record<string, unknown> = { input: params.input };
    if (params.sessionId) body.session_id = params.sessionId;
    if (params.projectId) body.project_id = params.projectId;
    if (params.model) body.model = params.model;
    const response = await apiClient.post<AgentRunCreateResponse>('/agent/runs', body, {
      timeout: 60000,
    });
    return response.data;
  },

  getRun: async (runId: string): Promise<AgentRunState> => {
    const response = await apiClient.get<AgentRunState>(`/agent/runs/${runId}`);
    return response.data;
  },

  submitApproval: async (
    runId: string,
    choice: ApprovalChoice,
    requestId?: string,
  ): Promise<{ resolved?: number }> => {
    const body: Record<string, unknown> = { choice };
    if (requestId) body.request_id = requestId;
    const response = await apiClient.post(`/agent/runs/${runId}/approval`, body, {
      timeout: 30000,
    });
    return response.data as { resolved?: number };
  },

  /** 停止运行中的 run（Hermes 侧 hard interrupt） */
  stopRun: async (runId: string): Promise<{ run_id?: string; status?: string }> => {
    const response = await apiClient.post(`/agent/runs/${runId}/stop`, {}, { timeout: 30000 });
    return response.data as { run_id?: string; status?: string };
  },

  /** 订阅 SSE；lastSeq 用于刷新后从断点续流 */
  streamRun: async (runId: string, handlers: StreamHandlers, lastSeq = 0): Promise<void> => {
    const query = lastSeq > 0 ? `?last_seq=${lastSeq}` : '';
    const response = await fetch(`${BASE}/runs/${runId}/events${query}`, {
      method: 'GET',
      headers: { Accept: 'text/event-stream' },
      signal: handlers.signal,
    });
    if (!response.ok || !response.body) {
      const detail = await response.text().catch(() => '');
      throw new Error(`SSE 连接失败 (HTTP ${response.status}) ${detail.slice(0, 200)}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    const feed = createSseParser(handlers.onEvent, handlers.onId);
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      feed(decoder.decode(value, { stream: true }));
    }
  },
};

export default agentApi;
