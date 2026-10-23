// Single message display
import React from 'react';
import { Avatar, Card, Typography, Tag } from 'antd';
import { UserOutlined, RobotOutlined } from '@ant-design/icons';
import type { Message } from '@/types/chat';
import type { ApprovalChoice } from '@/types/agent';
import ReasoningChain from './ReasoningChain';
import ApprovalCard from './ApprovalCard';

const { Paragraph, Text } = Typography;

interface MessageItemProps {
  message: Message;
  onApprovalDecide?: (messageId: string, choice: ApprovalChoice) => void;
}

const MessageItem: React.FC<MessageItemProps> = ({ message, onApprovalDecide }) => {
  const isUser = message.role === 'user';

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 16,
      }}
    >
      <div
        style={{
          display: 'flex',
          gap: 12,
          maxWidth: '80%',
          flexDirection: isUser ? 'row-reverse' : 'row',
        }}
      >
        <Avatar
          icon={isUser ? <UserOutlined /> : <RobotOutlined />}
          style={{
            backgroundColor: isUser ? '#1890ff' : '#52c41a',
          }}
        />
        <Card
          size="small"
          style={{
            background: isUser ? '#e6f7ff' : '#f5f5f5',
          }}
          bodyStyle={{ padding: '12px 16px' }}
        >
          {message.taskType && (
            <Tag style={{ marginBottom: 8 }}>{message.taskType}</Tag>
          )}
          <Paragraph
            style={{ margin: 0, whiteSpace: 'pre-wrap' }}
          >
            {message.content}
          </Paragraph>
          {message.reasoningTrace && message.reasoningTrace.length > 0 && (
            <ReasoningChain steps={message.reasoningTrace} />
          )}
          {message.progress && message.progress.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {message.progress.slice(-4).map((item, index) => (
                <div key={`${item}-${index}`}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{item}</Text>
                </div>
              ))}
            </div>
          )}
          {message.approval && (
            <ApprovalCard
              approval={message.approval}
              busy={message.approval.status === 'pending' && Boolean(message.approval.error)}
              onDecide={(choice) => onApprovalDecide?.(message.id, choice)}
            />
          )}
          <div style={{ marginTop: 8, textAlign: 'right' }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {new Date(message.timestamp).toLocaleTimeString()}
            </Typography.Text>
          </div>
        </Card>
      </div>
    </div>
  );
};

export default MessageItem;
