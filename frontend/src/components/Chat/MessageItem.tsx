// Single message display：用户右对齐浅主色底 / 助手左对齐白底描边
import React from 'react';
import { Tag } from 'antd';
import { UserOutlined, RobotOutlined } from '@ant-design/icons';
import type { Message } from '@/types/chat';
import type { ApprovalChoice } from '@/types/agent';
import ReasoningChain from './ReasoningChain';
import ApprovalCard from './ApprovalCard';

interface MessageItemProps {
  message: Message;
  onApprovalDecide?: (messageId: string, requestId: string, choice: ApprovalChoice) => void;
}

const MessageItem: React.FC<MessageItemProps> = ({ message, onApprovalDecide }) => {
  const isUser = message.role === 'user';

  return (
    <div className="hx-msg-row" data-role={isUser ? 'user' : 'assistant'}>
      <div className="hx-msg-avatar">
        {isUser ? <UserOutlined /> : <RobotOutlined />}
      </div>
      <div className="hx-msg-body">
        <div className="hx-bubble">
          {message.taskType && (
            <Tag style={{ marginBottom: 8 }} color="blue">
              {message.taskType}
            </Tag>
          )}
          {message.content}
          {message.reasoningTrace && message.reasoningTrace.length > 0 && (
            <ReasoningChain steps={message.reasoningTrace} />
          )}
          {message.progress && message.progress.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {message.progress.slice(-4).map((item, index) => (
                <div key={`${item}-${index}`} className="hx-muted">
                  {item}
                </div>
              ))}
            </div>
          )}
          {message.approvals?.map((approval) => (
            <ApprovalCard
              key={approval.requestId}
              approval={approval}
              busy={approval.status === 'pending' && Boolean(approval.error)}
              onDecide={(choice) => onApprovalDecide?.(message.id, approval.requestId, choice)}
            />
          ))}
        </div>
        <div className="hx-msg-meta">
          <span>{new Date(message.timestamp).toLocaleTimeString()}</span>
        </div>
      </div>
    </div>
  );
};

export default MessageItem;
