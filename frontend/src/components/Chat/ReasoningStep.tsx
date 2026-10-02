// Single reasoning step display
import React from 'react';
import { Card, Tag, Typography, Collapse, Space } from 'antd';
import {
  BulbOutlined,
  ThunderboltOutlined,
  EyeOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import type { ReasoningStep as ReasoningStepType } from '@/types/chat';

const { Text, Paragraph } = Typography;
const { Panel } = Collapse;

interface ReasoningStepProps {
  step: ReasoningStepType;
}

const ReasoningStep: React.FC<ReasoningStepProps> = ({ step }) => {
  const getStepIcon = () => {
    if (step.is_error) return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    if (step.observation) return <EyeOutlined style={{ color: '#52c41a' }} />;
    if (step.action) return <ThunderboltOutlined style={{ color: '#1890ff' }} />;
    return <BulbOutlined style={{ color: '#faad14' }} />;
  };

  const getStepLabel = () => {
    if (step.is_error) return '错误';
    if (step.observation) return '观察';
    if (step.action) return '执行';
    return '思考';
  };

  const getStepColor = () => {
    if (step.is_error) return 'error';
    if (step.observation) return 'success';
    if (step.action) return 'processing';
    return 'warning';
  };

  return (
    <Card
      size="small"
      style={{ marginBottom: 8 }}
      bodyStyle={{ padding: '8px 12px' }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ marginTop: 4 }}>{getStepIcon()}</div>
        <div style={{ flex: 1 }}>
          <Space style={{ marginBottom: 4 }}>
            <Tag color={getStepColor()}>{getStepLabel()}</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              步骤 {step.step_id}
            </Text>
            {step.duration_ms && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {step.duration_ms}ms
              </Text>
            )}
          </Space>
          <Collapse ghost size="small">
            <Panel header={<Text ellipsis style={{ maxWidth: 500 }}>{step.thought}</Text>} key="1">
              {step.action && (
                <div style={{ marginBottom: 8 }}>
                  <Text strong>动作: </Text>
                  <Tag>{step.action}</Tag>
                  {step.action_input && Object.keys(step.action_input).length > 0 && (
                    <Paragraph
                      code
                      style={{ marginTop: 4, marginBottom: 0, fontSize: 12 }}
                    >
                      {JSON.stringify(step.action_input, null, 2)}
                    </Paragraph>
                  )}
                </div>
              )}
              {step.observation && (
                <div>
                  <Text strong>观察: </Text>
                  <Paragraph
                    style={{ marginTop: 4, marginBottom: 0, whiteSpace: 'pre-wrap' }}
                  >
                    {step.observation}
                  </Paragraph>
                </div>
              )}
            </Panel>
          </Collapse>
        </div>
      </div>
    </Card>
  );
};

export default ReasoningStep;
