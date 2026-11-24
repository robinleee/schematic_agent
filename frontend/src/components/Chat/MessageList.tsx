// Message list display
import React, { useEffect, useRef } from 'react';
import { Spin } from 'antd';
import { CommentOutlined } from '@ant-design/icons';
import type { Message } from '@/types/chat';
import type { ApprovalChoice } from '@/types/agent';
import MessageItem from './MessageItem';

interface MessageListProps {
  messages: Message[];
  isLoading?: boolean;
  onApprovalDecide?: (messageId: string, requestId: string, choice: ApprovalChoice) => void;
  /** 点击示例问题 → 回填输入框 */
  onPickExample?: (question: string) => void;
}

const EXAMPLES = [
  'U30004 的引脚都连到哪些网络？',
  '帮我审查当前项目有没有电源完整性问题',
  'TPS7A47 的输出耐压余量够吗？',
  '为什么 VDD_DES_1V8_LARK 上电失败？',
];

const MessageList: React.FC<MessageListProps> = ({
  messages,
  isLoading,
  onApprovalDecide,
  onPickExample,
}) => {
  const listEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  if (messages.length === 0 && !isLoading) {
    return (
      <div className="hx-messages">
        <div className="hx-chat-empty">
          <div className="hx-chat-empty-icon">
            <CommentOutlined />
          </div>
          <div className="hx-chat-empty-title">
            问点什么？我可以查图谱、跑审查、做故障诊断。
          </div>
          <div className="hx-chat-empty-sub">直接输入问题，或从下面挑一个开始</div>
          <div className="hx-chips">
            {EXAMPLES.map((question) => (
              <button
                key={question}
                type="button"
                className="hx-chip"
                onClick={() => onPickExample?.(question)}
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="hx-messages">
      {messages.map((msg) => (
        <MessageItem key={msg.id} message={msg} onApprovalDecide={onApprovalDecide} />
      ))}
      {isLoading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 38 }}>
          <Spin size="small" />
          <span className="hx-muted">AI 正在思考…</span>
        </div>
      )}
      <div ref={listEndRef} />
    </div>
  );
};

export default MessageList;
