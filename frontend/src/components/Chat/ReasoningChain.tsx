// Reasoning chain display
import React from 'react';
import { Collapse } from 'antd';
import ReasoningStep from './ReasoningStep';
import type { ReasoningStep as ReasoningStepType } from '@/types/chat';

const { Panel } = Collapse;

interface ReasoningChainProps {
  steps: ReasoningStepType[];
}

const ReasoningChain: React.FC<ReasoningChainProps> = ({ steps }) => {
  if (!steps || steps.length === 0) return null;

  return (
    <Collapse
      ghost
      defaultActiveKey={['1']}
      style={{ marginTop: 8 }}
    >
      <Panel header={`推理链路 (${steps.length} 步)`} key="1">
        {steps.map((step) => (
          <ReasoningStep key={step.step_id} step={step} />
        ))}
      </Panel>
    </Collapse>
  );
};

export default ReasoningChain;
