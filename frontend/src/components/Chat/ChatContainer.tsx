// Chat container component
import React, { useCallback, useRef, useState } from 'react';
import { Button, Space, Typography, Card, Switch, Select, Tooltip } from 'antd';
import { ClearOutlined, ExperimentOutlined } from '@ant-design/icons';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import { useChatStore } from '@/stores';
import { useProjectStore } from '@/stores/useProjectStore';
import { chatApi, agentApi } from '@/api';
import type { Message, ReasoningStep } from '@/types/chat';
import type { AgentRunEvent, ApprovalChoice, ApprovalState } from '@/types/agent';
import { useChatWebSocket } from '@/hooks/useWebSocket';
import { apiErrorText } from '@/api/client';

const { Title } = Typography;

type Engine = 'legacy' | 'hermes';

/** 审批倒计时，超时前端自动拒绝（后端仍会等，绝不会自动放行） */
const APPROVAL_TTL_MS = 180_000;

const ChatContainer: React.FC = () => {
  const { messages, isLoading, setLoading, addMessage, updateLastAssistantMessage, updateMessage, clearMessages } = useChatStore();
  const currentProject = useProjectStore((state) => state.currentProject);
  // "default" is the frontend's sentinel for the shared/aggregate graph;
  // the backend's aggregate view is project_id=None, not a project literally named "default".
  const scopedProjectId = currentProject === 'default' ? undefined : currentProject;
  const [streaming, setStreaming] = useState(false);
  const [engine, setEngine] = useState<Engine>('legacy');
  const trace = useRef<ReasoningStep[]>([]);
  const busy = useRef(false);
  // Hermes 引擎：一个浏览器会话对应一个 Hermes session_id
  const sessionId = useRef<string>(
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `web-${Date.now()}`,
  );
  const abortRef = useRef<AbortController | null>(null);
  const finish = useCallback(() => { busy.current = false; setLoading(false); }, [setLoading]);
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

  const handleHermesSend = useCallback(async (message: string, taskType?: string) => {
    const assistantId = `assistant-${Date.now()}`;
    let text = '';
    let progress: string[] = [];
    let lastTool: string | undefined;

    const patch = (extra: Partial<Message> = {}) => {
      updateMessage(assistantId, { content: text || '正在处理…', progress: [...progress], ...extra });
    };

    addMessage({
      id: assistantId, role: 'assistant', content: '正在处理…',
      timestamp: new Date().toISOString(), reasoningTrace: [], taskType, progress: [],
    });

    const onEvent = (event: AgentRunEvent) => {
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
            runId: event.run_id ?? '',
            requestId: event.request_id ?? '',
            tool: lastTool,
            command: event.command,
            description: event.description,
            choices: (event.choices ?? ['once', 'deny']) as ApprovalChoice[],
            status: 'pending',
            deadline: Date.now() + APPROVAL_TTL_MS,
          };
          progress = [...progress, `等待审批：${lastTool ?? '写工具'}`];
          patch({ approval });
          break;
        }
        case 'run.completed':
          if (!text && event.output) text = event.output;
          patch({ content: text || '（本轮没有文本输出）' });
          abortRef.current = null;
          finish();
          break;
        default:
          break;
      }
    };

    try {
      const run = await agentApi.createRun({
        input: message,
        sessionId: sessionId.current,
        projectId: scopedProjectId,
      });
      // 审批卡片需要 run_id 才能回传决定
      const runId = run.run_id;
      const originalOnEvent = onEvent;
      const controller = new AbortController();
      abortRef.current = controller;
      await agentApi.streamRun(runId, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.event === 'approval.request' && !event.run_id) event.run_id = runId;
          originalOnEvent(event);
        },
      });
    } catch (error) {
      updateMessage(assistantId, {
        content: `${text}\n\n发生错误：${apiErrorText(error)}`.trim(),
      });
      finish();
    }
  }, [addMessage, updateMessage, finish, scopedProjectId]);

  const handleApprovalDecide = useCallback(async (messageId: string, choice: ApprovalChoice) => {
    const target = useChatStore.getState().messages.find((item) => item.id === messageId);
    const approval = target?.approval;
    if (!approval || approval.status !== 'pending') return;

    const expired = Boolean(approval.deadline && Date.now() >= approval.deadline);
    const effective: ApprovalChoice = expired ? 'deny' : choice;

    updateMessage(messageId, { approval: { ...approval, choice: effective } });
    try {
      await agentApi.submitApproval(approval.runId, effective, approval.requestId);
      updateMessage(messageId, {
        approval: {
          ...approval,
          choice: effective,
          status: expired ? 'expired' : effective === 'deny' ? 'denied' : 'approved',
        },
      });
    } catch (error) {
      updateMessage(messageId, {
        approval: { ...approval, status: 'error', error: apiErrorText(error) },
      });
    }
  }, [updateMessage]);

  const handleSend = useCallback(async (message: string, taskType?: string) => {
    // Add user message
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
      taskType,
    };
    addMessage(userMessage);
    setLoading(true);

    if (engine === 'hermes') {
      busy.current = true;
      await handleHermesSend(message, taskType);
      return;
    }

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

      // Add assistant message
      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.data.report || `状态：${response.data.status}`,
        timestamp: response.timestamp,
        reasoningTrace: response.data.execution_trace,
        taskType: response.data.task_type,
      };
      addMessage(assistantMessage);
    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `发生错误: ${apiErrorText(error)}`,
        timestamp: new Date().toISOString(),
      };
      addMessage(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [addMessage, setLoading, streaming, send, updateLastAssistantMessage, finish, scopedProjectId,
      engine, handleHermesSend]);

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
                style={{ width: 130 }}
                onChange={(value: Engine) => {
                  setEngine(value);
                  if (value === 'hermes' && streaming) { setStreaming(false); disconnect(); }
                }}
                disabled={isLoading}
                options={[
                  { value: 'legacy', label: '经典引擎' },
                  { value: 'hermes', label: 'Hermes 引擎' },
                ]}
              />
            </Space>
          </Tooltip>
          {engine === 'legacy' && (
            <>
              <span>流式对话 {streaming && (isConnected ? '已连接' : '连接中')}</span>
              <Switch checked={streaming} onChange={(checked) => {
                setStreaming(checked);
                if (checked) connect(); else disconnect();
              }} disabled={isLoading} />
            </>
          )}
          <Button icon={<ClearOutlined />} onClick={clearMessages}>
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
