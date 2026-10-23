// 审批卡片：Hermes 触发写工具时展示，倒计时结束自动拒绝
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Space, Tag, Typography } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  FieldTimeOutlined,
} from '@ant-design/icons';
import type { ApprovalChoice, ApprovalState } from '@/types/agent';
import { APPROVAL_LABELS } from '@/types/agent';

const { Text, Paragraph } = Typography;

interface ApprovalCardProps {
  approval: ApprovalState;
  onDecide: (choice: ApprovalChoice) => void;
  busy?: boolean;
}

const DANGER_CHOICES: ApprovalChoice[] = ['deny'];

const ApprovalCard: React.FC<ApprovalCardProps> = ({ approval, onDecide, busy }) => {
  const pending = approval.status === 'pending';
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!pending || !approval.deadline) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [pending, approval.deadline]);

  const remaining = useMemo(() => {
    if (!approval.deadline) return null;
    return Math.max(0, Math.ceil((approval.deadline - now) / 1000));
  }, [approval.deadline, now]);

  useEffect(() => {
    if (pending && remaining === 0) onDecide('deny');
  }, [pending, remaining, onDecide]);

  const decisionTag = () => {
    if (approval.status === 'approved') {
      return <Tag icon={<CheckCircleOutlined />} color="success">已允许（{approval.choice ? APPROVAL_LABELS[approval.choice] : '—'}）</Tag>;
    }
    if (approval.status === 'denied') {
      return <Tag icon={<CloseCircleOutlined />} color="default">已拒绝</Tag>;
    }
    if (approval.status === 'expired') {
      return <Tag icon={<FieldTimeOutlined />} color="warning">超时自动拒绝</Tag>;
    }
    if (approval.status === 'error') {
      return <Tag icon={<CloseCircleOutlined />} color="error">提交失败</Tag>;
    }
    return null;
  };

  return (
    <Card
      size="small"
      style={{
        marginTop: 12,
        borderColor: pending ? '#faad14' : '#d9d9d9',
        background: pending ? '#fffbe6' : '#fafafa',
      }}
      bodyStyle={{ padding: 12 }}
    >
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space wrap>
          <ExclamationCircleOutlined style={{ color: '#faad14' }} />
          <Text strong>需要你确认</Text>
          {approval.tool && <Tag color="blue">{approval.tool}</Tag>}
          {decisionTag()}
          {pending && remaining !== null && (
            <Tag icon={<FieldTimeOutlined />} color={remaining <= 30 ? 'red' : 'default'}>
              {remaining}s 后自动拒绝
            </Tag>
          )}
        </Space>

        <Paragraph style={{ margin: 0 }}>
          Hermes 请求执行写工具，该操作会修改外部状态，需要你放行。
        </Paragraph>
        {(approval.description || approval.command) && (
          <Paragraph
            style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 12 }}
            type="secondary"
            ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
          >
            {approval.description || approval.command}
          </Paragraph>
        )}

        {approval.error && (
          <Alert type="error" showIcon message={approval.error} />
        )}

        {pending && (
          <Space wrap>
            {approval.choices.map((choice) => (
              <Button
                key={choice}
                size="small"
                type={choice === 'once' ? 'primary' : 'default'}
                danger={DANGER_CHOICES.includes(choice)}
                loading={busy}
                onClick={() => onDecide(choice)}
              >
                {APPROVAL_LABELS[choice] ?? choice}
              </Button>
            ))}
          </Space>
        )}
      </Space>
    </Card>
  );
};

export default ApprovalCard;
