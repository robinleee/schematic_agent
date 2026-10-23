// Chat container component
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Space, Typography, Card, Switch, Select, Tooltip, Tag } from 'antd';
import { ClearOutlined, ExperimentOutlined, StopOutlined } from '@ant-design/icons';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import { useChatStore } from '@/stores';
import { useProjectStore } from '@/stores/useProjectStore';
import { chatApi, agentApi } from '@/api';
import type { Message, ReasoningStep } from '@/types/chat';
import type { AgentHealth, AgentRunEvent, ApprovalChoice, ApprovalState } from '@/types/agent';
import { useChatWebSocket } from '@/hooks/useWebSocket';
import { apiErrorText } from '@/api/client';

const { Title } = Typography;

type Engine = 'legacy' | 'hermes';

/** 审批倒计时，超时前端自动拒绝（后端仍会等，绝不会自动放行） */
const APPROVAL_TTL_MS = 180_000;

/** Hermes 侧不可用（未开启 / 网关不通 / 代理 5xx），需要回退经典引擎 */
function isHermesUnavailable(error: unknown): boolean {
  const text = apiErrorText(error);
  return /HTTP (502|503|504)|SSE 连接失败|Hermes 网关不可用|灰度未开启/.test(text);
}

const ChatContainer: React.FC = () => {
  const { messages, isLoading, setLoading, addMessage, updateLastAssistantMessage, updateMessage, clearMessages } = useChatStore();
  const currentProject = useProjectStore((state) => state.currentProject);
  // "default" is the frontend's sentinel for the shared/aggregate graph;
  // the backend's aggregate view is project_id=None, not a project literally named "default".
  const scopedProjectId = currentProject === 'default' ? undefined : currentProject;
  const [streaming, setStreaming] = useState(false);
  const [engine, setEngine] = useState<Engine>('legacy');
  const [health, setHealth] = useState<AgentHealth | null>(null);
  const trace = useRef<ReasoningStep[]>([]);
  const busy = useRef(false);
  // Hermes 引擎：一个浏览器会话对应一个 conversation（后端再拼成 user:project:conversation）
  // 按项目持久化，刷新页面不会换会话，否则 Hermes 侧记忆会断。
  const sessionId = useRef<string>('');
  const sessionStorageKey = `schematic:hermes:session:${currentProject}`;

  const newConversationId = () =>
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `web-${Date.now()}`;

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(sessionStorageKey);
      if (stored) {
        sessionId.current = stored;
        return;
      }
      const created = newConversationId();
      window.localStorage.setItem(sessionStorageKey, created);
      sessionId.current = created;
    } catch {
      sessionId.current = newConversationId();
    }
  }, [sessionStorageKey]);

  /** 清空对话 = 换新会话（旧会话的记忆不再串到新话题） */
  const rotateSession = useCallback(() => {
    const created = typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `web-${Date.now()}`;
    sessionId.current = created;
    try {
      window.localStorage.setItem(`schematic:hermes:session:${currentProject}`, created);
    } catch {
      /* 隐私模式下写不了 localStorage，退化为内存会话 */
    }
  }, [currentProject]);
  const abortRef = useRef<AbortController | null>(null);
  // 进行中的 Hermes run：停止按钮和刷新恢复都靠它
  const activeRun = useRef<{ runId: string; messageId: string; lastSeq: number } | null>(null);
  const activeRunKey = `schematic:hermes:activeRun:${currentProject}`;
  const persistActiveRun = useCallback((value: { runId: string; messageId: string; lastSeq: number } | null) => {
    try {
      if (value) window.localStorage.setItem(activeRunKey, JSON.stringify(value));
      else window.localStorage.removeItem(activeRunKey);
    } catch {
      /* 隐私模式忽略 */
    }
  }, [activeRunKey]);
  const finish = useCallback(() => { busy.current = false; setLoading(false); }, [setLoading]);

  useEffect(() => {
    let alive = true;
    agentApi.health()
      .then((result) => { if (alive) setHealth(result); })
      .catch(() => { if (alive) setHealth(null); });
    return () => { alive = false; };
  }, []);

  const { connect, disconnect, send, isConnected } = useChatWebSocket({
    onStep: (step) => {
      trace.current = [...trace.current, step];
      updateLastAssistantMessage('正在推理…', trace.current);
    },
    onResult: (result) => {
      updateLastAssistantMessage(result.report || `状态：${result.status}`,
        result.execution_trace?.length ? result.execution_trace : trace.current);
      finish();
    },
    onError: (error) => {
      if (busy.current) {
        updateLastAssistantMessage(`发生错误：${error}`, trace.current);
        finish();
      }
    },
  });

  /** 订阅一个已存在的 run 并把事件写进指定消息（新建与刷新恢复共用） */
  const attachRun = useCallback(async (
    runId: string, assistantId: string, startSeq = 0,
  ) => {
    let text = '';
    let progress: string[] = [];
    let lastTool: string | undefined;

    const patch = (extra: Partial<Message> = {}) => {
      updateMessage(assistantId, { content: text || '正在处理…', progress: [...progress], ...extra });
    };

    const applyEvent = (event: AgentRunEvent) => {
      switch (event.event) {
        case 'message.delta':
          text += event.delta ?? '';
          patch();
          break;
        case 'tool.started':
          lastTool = event.tool;
          progress = [...progress, `调用工具：${event.tool}`];
          patch();
          break;
        case 'tool.completed': {
          const label = event.error ? '失败' : '完成';
          progress = [...progress, `工具${label}：${event.tool}${event.duration ? ` (${event.duration}s)` : ''}`];
          patch();
          break;
        }
        case 'approval.request': {
          const approval: ApprovalState = {
            runId: event.run_id ?? runId,
            requestId: event.request_id ?? '',
            tool: lastTool,
            command: event.command,
            description: event.description,
            choices: (event.choices ?? ['once', 'deny']) as ApprovalChoice[],
            status: 'pending',
            deadline: Date.now() + APPROVAL_TTL_MS,
          };
          progress = [...progress, `等待审批：${lastTool ?? '写工具'}`];
          const existing = useChatStore.getState().messages.find((m) => m.id === assistantId)?.approvals ?? [];
          patch({ approvals: [...existing, approval] });
          break;
        }
        case 'run.completed':
          if (!text && event.output) text = event.output;
          patch({ content: text || '（本轮没有文本输出）' });
          abortRef.current = null;
          activeRun.current = null;
          persistActiveRun(null);
          finish();
          break;
        default:
          break;
      }
    };

    const controller = new AbortController();
    abortRef.current = controller;
    activeRun.current = { runId, messageId: assistantId, lastSeq: startSeq };
    persistActiveRun({ runId, messageId: assistantId, lastSeq: startSeq });

    try {
      await agentApi.streamRun(runId, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.event === 'approval.request' && !event.run_id) event.run_id = runId;
          applyEvent(event);
        },
        onId: (seq) => {
          if (!activeRun.current) return;
          activeRun.current = { ...activeRun.current, lastSeq: seq };
          persistActiveRun(activeRun.current);
        },
      }, startSeq);
    } catch (error) {
      if (controller.signal.aborted) {
        // 用户主动停止，状态已在 stopHermes 里写好了
        return;
      }
      updateMessage(assistantId, {
        content: `${text}\n\n事件流中断：${apiErrorText(error)}`.trim(),
      });
      persistActiveRun(null);
      activeRun.current = null;
      finish();
    }
  }, [updateMessage, finish, persistActiveRun]);

  const runHermes = useCallback(async (message: string, taskType?: string) => {
    const assistantId = `assistant-${Date.now()}`;
    addMessage({
      id: assistantId, role: 'assistant', content: '正在处理…',
      timestamp: new Date().toISOString(), reasoningTrace: [], taskType, progress: [],
    });

    // 创建失败会抛给上层，由 handleSend 决定是否回退经典引擎
    const run = await agentApi.createRun({
      input: message,
      sessionId: sessionId.current,
      projectId: scopedProjectId,
    });
    await attachRun(run.run_id, assistantId);
  }, [addMessage, attachRun, scopedProjectId]);

  /** 停止：先让 Hermes 硬中断，再本地收尾（绝不把半截输出当成完成） */
  const stopHermes = useCallback(async () => {
    const active = activeRun.current;
    if (!active) return;
    try {
      await agentApi.stopRun(active.runId);
    } catch {
      /* 上游可能已结束，仍按本地停止处理 */
    }
    abortRef.current?.abort();
    abortRef.current = null;
    const current = useChatStore.getState().messages.find((m) => m.id === active.messageId);
    updateMessage(active.messageId, {
      content: `${current?.content ?? ''}\n\n（已停止）`.trim(),
      progress: [...(current?.progress ?? []), '用户停止'],
    });
    activeRun.current = null;
    persistActiveRun(null);
    finish();
  }, [updateMessage, finish, persistActiveRun]);

  // 刷新后恢复上次未完成的 run（只尝试一次）
  const resumeAttempted = useRef(false);
  useEffect(() => {
    if (resumeAttempted.current) return;
    let raw: string | null = null;
    try {
      raw = window.localStorage.getItem(activeRunKey);
    } catch {
      return;
    }
    if (!raw) return;
    resumeAttempted.current = true;

    let saved: { runId: string; messageId: string; lastSeq: number } | null = null;
    try {
      saved = JSON.parse(raw) as { runId: string; messageId: string; lastSeq: number };
    } catch {
      persistActiveRun(null);
      return;
    }
    if (!saved?.runId) { persistActiveRun(null); return; }

    const assistantId = `assistant-${Date.now()}`;
    (async () => {
      try {
        const state = await agentApi.getRun(saved!.runId);
        const terminal = ['completed', 'failed', 'cancelled', 'stopped'].includes(state.status);
        if (terminal) {
          addMessage({
            id: assistantId, role: 'assistant',
            content: state.output || '上次的会话已结束（没有取到输出）',
            timestamp: new Date().toISOString(), reasoningTrace: [], progress: [],
          });
          persistActiveRun(null);
          activeRun.current = null;
          return;
        }
        setEngine('hermes');
        setLoading(true);
        busy.current = true;
        addMessage({
          id: assistantId, role: 'assistant', content: '正在恢复上次运行…',
          timestamp: new Date().toISOString(), reasoningTrace: [], progress: [],
        });
        await attachRun(saved!.runId, assistantId, saved!.lastSeq || 0);
      } catch (error) {
        persistActiveRun(null);
        activeRun.current = null;
        addMessage({
          id: `notice-${Date.now()}`, role: 'assistant',
          content: `上次的会话已结束（${apiErrorText(error)}）`,
          timestamp: new Date().toISOString(),
        });
        finish();
      }
    })();
    // 只在挂载/切项目时跑一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRunKey]);

  const handleApprovalDecide = useCallback(async (
    messageId: string, requestId: string, choice: ApprovalChoice,
  ) => {
    const target = useChatStore.getState().messages.find((item) => item.id === messageId);
    const approval = target?.approvals?.find((item) => item.requestId === requestId);
    if (!approval || approval.status !== 'pending') return;

    const expired = Boolean(approval.deadline && Date.now() >= approval.deadline);
    const effective: ApprovalChoice = expired ? 'deny' : choice;
    const patch = (extra: Partial<ApprovalState>) => {
      const list = useChatStore.getState().messages
        .find((item) => item.id === messageId)?.approvals ?? [];
      updateMessage(messageId, {
        approvals: list.map((item) => (item.requestId === requestId ? { ...item, ...extra } : item)),
      });
    };

    patch({ choice: effective });
    try {
      await agentApi.submitApproval(approval.runId, effective, approval.requestId);
      patch({ status: expired ? 'expired' : effective === 'deny' ? 'denied' : 'approved' });
    } catch (error) {
      patch({ status: 'error', error: apiErrorText(error) });
    }
  }, [updateMessage]);

  const runLegacy = useCallback(async (message: string, taskType?: string) => {
    if (streaming) {
      trace.current = [];
      addMessage({ id: `assistant-${Date.now()}`, role: 'assistant', content: '正在推理…',
        timestamp: new Date().toISOString(), reasoningTrace: [], taskType });
      busy.current = true;
      if (!send(message, taskType, scopedProjectId)) {
        updateLastAssistantMessage('WebSocket 尚未连接，请稍后重试或关闭流式模式');
        finish();
      }
      return;
    }

    try {
      const response = await chatApi.sendMessage({
        message,
        task_type: taskType as 'review' | 'diagnosis' | 'query' | 'auto' | undefined,
        project_id: scopedProjectId,
      });
      addMessage({
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.data.report || `状态：${response.data.status}`,
        timestamp: response.timestamp,
        reasoningTrace: response.data.execution_trace,
        taskType: response.data.task_type,
      });
    } catch (error) {
      console.error('Chat error:', error);
      addMessage({
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `发生错误: ${apiErrorText(error)}`,
        timestamp: new Date().toISOString(),
      });
    } finally {
      setLoading(false);
    }
  }, [addMessage, setLoading, streaming, send, updateLastAssistantMessage, finish, scopedProjectId]);

  const handleSend = useCallback(async (message: string, taskType?: string) => {
    addMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
      taskType,
    });
    setLoading(true);

    if (engine === 'hermes') {
      busy.current = true;
      try {
        await runHermes(message, taskType);
        return;
      } catch (error) {
        if (!isHermesUnavailable(error)) {
          addMessage({
            id: `error-${Date.now()}`,
            role: 'assistant',
            content: `Hermes 引擎出错：${apiErrorText(error)}`,
            timestamp: new Date().toISOString(),
          });
          finish();
          return;
        }
        setEngine('legacy');
        setHealth((prev) => (prev ? { ...prev, upstream: false } : prev));
        // 回退是验收门指标，必须留下痕迹（失败静默）
        void agentApi.telemetry({
          event: 'hermes.fallback',
          detail: apiErrorText(error).slice(0, 200),
          projectId: scopedProjectId,
        });
        addMessage({
          id: `notice-${Date.now()}`,
          role: 'assistant',
          content: `Hermes 引擎不可用（${apiErrorText(error)}），已自动切回经典引擎重试。`,
          timestamp: new Date().toISOString(),
        });
        setStreaming(false);
        disconnect();
      }
    }

    await runLegacy(message, taskType);
  }, [addMessage, setLoading, engine, runHermes, finish, runLegacy, disconnect]);

  const hermesAvailable = health ? health.enabled : false;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>智能对话（项目：{currentProject}）</Title>
        <Space>
          <Tooltip title="Hermes 为灰度引擎：支持 MCP 工具审批与流式事件；经典引擎为现有 ReAct 链路">
            <Space size={4}>
              <ExperimentOutlined />
              <Select
                size="small"
                value={engine}
                style={{ width: 150 }}
                onChange={(value: Engine) => {
                  setEngine(value);
                  if (value === 'hermes' && streaming) { setStreaming(false); disconnect(); }
                }}
                disabled={isLoading}
                options={[
                  { value: 'legacy', label: '经典引擎' },
                  {
                    value: 'hermes',
                    label: hermesAvailable ? 'Hermes 引擎' : 'Hermes（未开启）',
                    disabled: !hermesAvailable,
                  },
                ]}
              />
            </Space>
          </Tooltip>
          {engine === 'hermes' && health && (
            <Tag color={health.upstream ? 'green' : 'red'}>
              {health.upstream ? '网关正常' : `网关不可用${health.detail ? `：${health.detail}` : ''}`}
            </Tag>
          )}
          {engine === 'hermes' && isLoading && (
            <Tooltip title="中断当前 Hermes 运行（服务端会回收工具子进程）">
              <Button danger size="small" icon={<StopOutlined />} onClick={stopHermes}>
                停止
              </Button>
            </Tooltip>
          )}
          {engine === 'legacy' && (
            <>
              <span>流式对话 {streaming && (isConnected ? '已连接' : '连接中')}</span>
              <Switch checked={streaming} onChange={(checked) => {
                setStreaming(checked);
                if (checked) connect(); else disconnect();
              }} disabled={isLoading} />
            </>
          )}
          <Button icon={<ClearOutlined />} onClick={() => { clearMessages(); rotateSession(); }}>
            清空对话
          </Button>
        </Space>
      </div>

      <Card style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }} bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 16 }}>
        <MessageList messages={messages} isLoading={isLoading} onApprovalDecide={handleApprovalDecide} />
        <div style={{ marginTop: 16 }}>
          <ChatInput onSend={handleSend} disabled={isLoading} />
        </div>
      </Card>
    </div>
  );
};

export default ChatContainer;
