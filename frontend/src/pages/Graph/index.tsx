// Graph visualization page
import React, { useState } from 'react';
import {
  Card,
  Select,
  InputNumber,
  Input,
  Button,
  Space,
  Typography,
  message,
  Empty,
  Spin,
} from 'antd';
import {
  PlayCircleOutlined,
} from '@ant-design/icons';
import { graphApi } from '@/api';
import { apiErrorText } from '@/api/client';
import type { VizMode, Direction } from '@/types/graph';
import DotView from './DotView';
import { parseDot, type DotGraph } from './dot';

const { Title, Text } = Typography;

const GraphPage: React.FC = () => {
  const [mode, setMode] = useState<VizMode>('component');
  const [refdes, setRefdes] = useState('');
  const [depth, setDepth] = useState(2);
  const [direction, setDirection] = useState<Direction>('both');
  const [voltage, setVoltage] = useState('');
  const [loading, setLoading] = useState(false);
  const [graph, setGraph] = useState<DotGraph | null>(null);
  const [status, setStatus] = useState('选择参数后点击「生成图谱」');

  const handleVisualize = async () => {
    if (!refdes && mode !== 'power_tree') {
      message.error('请输入起始器件');
      return;
    }

    setGraph(null);
    setStatus('');
    setLoading(true);
    try {
      const response = await graphApi.visualize({
        mode,
        refdes: refdes || undefined,
        depth,
        direction,
        voltage: voltage || undefined,
      });
      if (!response.success) throw new Error(response.message || '接口返回失败');
      const parsed = parseDot(response.data?.dot_content);
      if (parsed.nodes.length === 0) {
        setStatus('查询成功，但图谱没有可显示的节点');
      } else {
        setGraph(parsed);
      }
    } catch (error) {
      setStatus(`图谱生成或渲染失败：${apiErrorText(error)}`);
    } finally {
      setLoading(false);
    }
  };

  const modeOptions = [
    { value: 'component', label: '组件关系' },
    { value: 'power_chain', label: '电源链路' },
    { value: 'fault_trace', label: '故障溯源' },
    { value: 'common_cause', label: '共因失效' },
    { value: 'power_tree', label: '电源树' },
  ];

  return (
    <div>
      <Title level={4}>图谱可视化</Title>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap style={{ width: '100%' }}>
          <Space>
            <Text>可视化模式:</Text>
            <Select
              value={mode}
              onChange={setMode}
              style={{ width: 150 }}
              options={modeOptions}
            />
          </Space>

          <Space>
            <Text>起始器件:</Text>
            <Input
              placeholder="例如: U30004"
              value={refdes}
              onChange={(e) => setRefdes(e.target.value)}
              style={{ width: 150 }}
            />
          </Space>

          <Space>
            <Text>深度:</Text>
            <InputNumber
              min={1}
              max={5}
              value={depth}
              onChange={(v) => setDepth(v || 2)}
            />
          </Space>

          <Space>
            <Text>方向:</Text>
            <Select
              value={direction}
              onChange={setDirection}
              style={{ width: 120 }}
              options={[
                { value: 'upstream', label: '上游' },
                { value: 'downstream', label: '下游' },
                { value: 'both', label: '双向' },
              ]}
            />
          </Space>

          {mode === 'power_tree' && (
            <Space>
              <Text>电压:</Text>
              <Input
                placeholder="例如: 3.3V"
                value={voltage}
                onChange={(e) => setVoltage(e.target.value)}
                style={{ width: 100 }}
              />
            </Space>
          )}

          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleVisualize}
            loading={loading}
          >
            生成图谱
          </Button>
        </Space>
      </Card>

      <Card
        title="图谱"
        extra={
          <Space>
            <Text>节点: {graph?.nodes.length || 0} | 边: {graph?.edges.length || 0}</Text>
          </Space>
        }
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: 100 }}>
            <Spin size="large" />
          </div>
        ) : graph ? (
          <DotView graph={graph} />
        ) : (
          <Empty description={status} />
        )}
      </Card>
    </div>
  );
};

export default GraphPage;
