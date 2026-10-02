// Chat input component
import React, { useState } from 'react';
import { Input, Button, Select } from 'antd';
import { SendOutlined } from '@ant-design/icons';

const { TextArea } = Input;

interface ChatInputProps {
  onSend: (message: string, taskType?: string) => void;
  disabled?: boolean;
}

const ChatInput: React.FC<ChatInputProps> = ({ onSend, disabled }) => {
  const [message, setMessage] = useState('');
  const [taskType, setTaskType] = useState<string | undefined>(undefined);

  const handleSend = () => {
    if (message.trim()) {
      onSend(message.trim(), taskType);
      setMessage('');
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
      <Select
        placeholder="任务类型"
        value={taskType}
        onChange={setTaskType}
        allowClear
        style={{ width: 120 }}
        options={[
          { value: 'review', label: '审查' },
          { value: 'diagnosis', label: '诊断' },
          { value: 'query', label: '查询' },
        ]}
      />
      <TextArea
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyPress={handleKeyPress}
        placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
        autoSize={{ minRows: 1, maxRows: 4 }}
        style={{ flex: 1 }}
        disabled={disabled}
      />
      <Button
        type="primary"
        icon={<SendOutlined />}
        onClick={handleSend}
        disabled={!message.trim() || disabled}
      >
        发送
      </Button>
    </div>
  );
};

export default ChatInput;
