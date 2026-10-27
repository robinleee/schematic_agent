// Graph visualization page
import React, { useState } from 'react';
import {
  Select,
  InputNumber,
  Input,
  Button,
  Typography,
  message,
  Spin,
} from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import { graphApi } from '@/api';
import { apiErrorText } from '@/api/client';
import type { VizMode, Direction } from '@/types/graph';
import DotView from './DotView';
import { parseDot, type DotGraph } from './dot';
import PageHeader from '@/components/common/PageHeader';

const { Text } = Typography;

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
    <div className="page">
      <PageHeader
        title="图谱可视化"
        description="从图数据库按模式抽取器件-网络子图，用于连通性核对、电源链路追踪与故障溯源。"
      />

      <section className="surface">
        <div className="toolbar">
          <div className="field">
            <span className="field-label">可视化模式</span>
            <Select
              value={mode}
              onChange={setMode}
              style={{ width: 156 }}
              options={modeOptions}
            />
          </div>

          <div className="field">
            <span className="field-label">
              起始器件{mode !== 'power_tree' ? <span style={{ color: 'var(--hx-error)' }}> *</span> : null}
            </span>
            <Input
              placeholder="例如：U30004"
              value={refdes}
              onChange={(e) => setRefdes(e.target.value)}
              onPressEnter={handleVisualize}
              style={{ width: 180 }}
            />
          </div>

          <div className="field">
            <span className="field-label">深度</span>
            <InputNumber
              min={1}
              max={5}
              value={depth}
              onChange={(v) => setDepth(v || 2)}
              style={{ width: 88 }}
            />
          </div>

          <div className="field">
            <span className="field-label">方向</span>
            <Select
              value={direction}
              onChange={setDirection}
              style={{ width: 110 }}
              options={[
                { value: 'upstream', label: '上游' },
                { value: 'downstream', label: '下游' },
                { value: 'both', label: '双向' },
              ]}
            />
          </div>

          {mode === 'power_tree' && (
            <div className="field">
              <span className="field-label">电压</span>
              <Input
                placeholder="例如：3.3V"
                value={voltage}
                onChange={(e) => setVoltage(e.target.value)}
                onPressEnter={handleVisualize}
                style={{ width: 120 }}
              />
            </div>
          )}

          <div className="toolbar-spacer" />

          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleVisualize}
            loading={loading}
            disabled={mode !== 'power_tree' && !refdes.trim()}
            title={mode !== 'power_tree' && !refdes.trim() ? '请先填写起始器件' : undefined}
          >
            生成图谱
          </Button>
        </div>
      </section>

      <section className="surface hx-graph-canvas">
        <div className="hx-graph-head">
          <span className="surface-title">图谱</span>
          <span className="hx-mono hx-muted">
            节点 {graph?.nodes.length || 0} · 边 {graph?.edges.length || 0}
          </span>
        </div>
        <div className="hx-graph-body">
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Spin size="large" />
            </div>
          ) : graph ? (
            <DotView graph={graph} />
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">
                <PlayCircleOutlined />
              </div>
              <div className="empty-state-text">{status}</div>
              <div className="empty-state-hint">
                提示：组件关系模式需要填写起始器件；电源树模式可只给电压
              </div>
            </div>
          )}
        </div>
      </section>

      {graph && (
        <Text className="hx-muted">
          画布可滚动查看全部节点；节点颜色来自 DOT 样式，鼠标悬停可看完整标签。
        </Text>
      )}
    </div>
  );
};

export default GraphPage;
