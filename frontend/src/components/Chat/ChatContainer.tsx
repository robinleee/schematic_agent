// Chat container component
import React, { useCallback, useRef, useState } from 'react';
import { Button, Space, Typography, Card, Switch } from 'antd';
import { ClearOutlined } from '@ant-design/icons';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import { useChatStore } from '@/stores';
import { useProjectStore } from '@/stores/useProjectStore';
import { chatApi } from '@/api';
import type { Message, ReasoningStep } from '@/types/chat';
import { useChatWebSocket } from '@/hooks/useWebSocket';
import { apiErrorText } from '@/api/client';

const { Title } = Typography;

const ChatContainer: React.FC = () => {
  const { messages, isLoading, setLoading, addMessage, updateLastAssistantMessage, clearMessages } = useChatStore();
  const currentProject = useProjectStore((state) => state.currentProject);
  // "default" is the frontend's sentinel for the shared/aggregate graph;
  // the backend's aggregate view is project_id=None, not a project literally named "default".
  const scopedProjectId = currentProject === 'default' ? undefined : currentProject;
  const [streaming, setStreaming] = useState(false);
  const trace = useRef<ReasoningStep[]>([]);
  const busy = useRef(false);
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
  }, [addMessage, setLoading, streaming, send, updateLastAssistantMessage, finish, scopedProjectId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>智能对话（项目：{currentProject}）</Title>
        <Space>
          <span>流式对话 {streaming && (isConnected ? '已连接' : '连接中')}</span>
          <Switch checked={streaming} onChange={(checked) => {
            setStreaming(checked);
            if (checked) connect(); else disconnect();
          }} disabled={isLoading} />
          <Button icon={<ClearOutlined />} onClick={clearMessages}>
            清空对话
          </Button>
        </Space>
      </div>
      
      <Card style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }} bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 16 }}>
        <MessageList messages={messages} isLoading={isLoading} />
        <div style={{ marginTop: 16 }}>
          <ChatInput onSend={handleSend} disabled={isLoading} />
        </div>
      </Card>
    </div>
  );
};

export default ChatContainer;
