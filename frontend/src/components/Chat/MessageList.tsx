// Message list display
import React, { useEffect, useRef } from 'react';
import { Empty, Spin } from 'antd';
import type { Message } from '@/types/chat';
import type { ApprovalChoice } from '@/types/agent';
import MessageItem from './MessageItem';

interface MessageListProps {
  messages: Message[];
  isLoading?: boolean;
  onApprovalDecide?: (messageId: string, requestId: string, choice: ApprovalChoice) => void;
}

const MessageList: React.FC<MessageListProps> = ({ messages, isLoading, onApprovalDecide }) => {
  const listEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (messages.length === 0 && !isLoading) {
    return (
      <Empty
        description="开始对话"
        style={{ marginTop: 100 }}
      />
    );
  }

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '16px 0' }}>
      {messages.map((msg) => (
        <MessageItem key={msg.id} message={msg} onApprovalDecide={onApprovalDecide} />
      ))}
      {isLoading && (
        <div style={{ textAlign: 'center', padding: 16 }}>
          <Spin tip="AI 正在思考..." />
        </div>
      )}
      <div ref={listEndRef} />
    </div>
  );
};

export default MessageList;
