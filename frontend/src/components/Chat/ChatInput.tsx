// Chat input component
import React, { useState } from 'react';
import { Input, Button, Select, Tooltip } from 'antd';
import { ArrowUpOutlined } from '@ant-design/icons';

const { TextArea } = Input;

interface ChatInputProps {
  onSend: (message: string, taskType?: string) => void;
  disabled?: boolean;
  /** 受控值（示例问题回填用）；不传则内部自管 */
  value?: string;
  onChange?: (value: string) => void;
}

const ChatInput: React.FC<ChatInputProps> = ({ onSend, disabled, value, onChange }) => {
  const [inner, setInner] = useState('');
  const [taskType, setTaskType] = useState<string | undefined>(undefined);
  const message = value ?? inner;

  const setMessage = (next: string) => {
    if (onChange) onChange(next);
    setInner(next);
  };

  const handleSend = () => {
    if (message.trim()) {
      onSend(message.trim(), taskType);
      setMessage('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = Boolean(message.trim()) && !disabled;

  return (
    <div>
      <div className="hx-composer-box">
        <Select
          variant="borderless"
          placeholder="任务类型"
          value={taskType}
          onChange={setTaskType}
          allowClear
          style={{ width: 104, flex: 'none' }}
          popupMatchSelectWidth={false}
          options={[
            { value: 'review', label: '审查' },
            { value: 'diagnosis', label: '诊断' },
            { value: 'query', label: '查询' },
          ]}
        />
        <TextArea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入问题…（Enter 发送，Shift+Enter 换行）"
          autoSize={{ minRows: 1, maxRows: 6 }}
          disabled={disabled}
          variant="borderless"
        />
        <Tooltip title="发送">
          <Button
            type="primary"
            shape="circle"
            aria-label="发送"
            icon={<ArrowUpOutlined />}
            onClick={handleSend}
            disabled={!canSend}
            style={{ flex: 'none', width: 32, height: 32, minWidth: 32 }}
          />
        </Tooltip>
      </div>
      <div className="hx-composer-hint">
        <span>Enter 发送 · Shift+Enter 换行</span>
        <span>·</span>
        <span>回答基于当前项目图谱与知识库，请自行复核关键结论</span>
      </div>
    </div>
  );
};

export default ChatInput;
