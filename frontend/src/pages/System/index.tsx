// System status page
import React, { useState, useEffect } from 'react';
import {
  Card,
  Typography,
  Statistic,
  Row,
  Col,
  Tag,
  Space,
  Button,
  Spin,
  Alert,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { systemApi } from '@/api';
import { apiErrorText } from '@/api/client';
import type { SystemStatus } from '@/types/system';

const { Title, Text } = Typography;

const SystemPage: React.FC = () => {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorText, setErrorText] = useState('');

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    setLoading(true);
    try {
      const response = await systemApi.getStatus();
      setStatus(response.data);
      setErrorText('');
    } catch (error) {
      setStatus(null);
      setErrorText(apiErrorText(error));
    } finally {
      setLoading(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'running':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'stopped':
        return <CloseCircleOutlined style={{ color: '#faad14' }} />;
      case 'error':
        return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
      case 'degraded':
        return <CloseCircleOutlined style={{ color: '#faad14' }} />;
      default:
        return null;
    }
  };

  const getStatusTag = (status: string) => {
    switch (status) {
      case 'running':
        return <Tag color="success">运行中</Tag>;
      case 'stopped':
        return <Tag color="warning">已停止</Tag>;
      case 'error':
        return <Tag color="error">错误</Tag>;
      case 'degraded':
        return <Tag color="warning">降级</Tag>;
      default:
        return <Tag>{status}</Tag>;
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      {errorText && <Alert type="error" showIcon message="系统状态获取失败" description={errorText} style={{ marginBottom: 16 }} />}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>系统状态</Title>
        <Button icon={<ReloadOutlined />} onClick={loadStatus}>
          刷新
        </Button>
      </div>

      <Card title="服务状态" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          {status?.services.map((service) => (
            <Col span={6} key={service.name}>
              <Card size="small">
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Space>
                    {getStatusIcon(service.status)}
                    <Text strong>{service.name}</Text>
                  </Space>
                  <div>
                    {getStatusTag(service.status)}
                    {service.latency_ms != null && (
                      <Tag>{service.latency_ms}ms</Tag>
                    )}
                    {service.version && (
                      <Tag>{service.version}</Tag>
                    )}
                  </div>
                  {service.message && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {service.message}
                    </Text>
                  )}
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      <Card title="数据统计" style={{ marginBottom: 16 }}>
        <Row gutter={24}>
          <Col span={6}>
            <Statistic title="器件数量" value={status?.data_stats.components ?? '不可用'} />
          </Col>
          <Col span={6}>
            <Statistic title="引脚数量" value={status?.data_stats.pins ?? '不可用'} />
          </Col>
          <Col span={6}>
            <Statistic title="网络数量" value={status?.data_stats.nets ?? '不可用'} />
          </Col>
          <Col span={6}>
            <Statistic
              title="PartType 覆盖率"
              value={status?.data_stats.part_type_coverage ?? '不可用'}
              suffix={status?.data_stats.part_type_coverage == null ? undefined : '%'}
            />
          </Col>
        </Row>
      </Card>

      <Card title="Agent 统计">
        <Row gutter={24}>
          <Col span={6}>
            <Statistic title="本进程 REST/WS 查询次数" value={status?.agent_stats.query_count ?? '不可用'} />
          </Col>
          <Col span={6}>
            <Statistic
              title="成功 / 失败"
              value={status ? `${status.agent_stats.success_count} / ${status.agent_stats.failure_count}` : '不可用'}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="平均耗时"
              value={status?.agent_stats.average_duration_ms ?? '不可用'}
              suffix={status?.agent_stats.average_duration_ms == null ? undefined : 'ms'}
            />
          </Col>
          <Col span={6}>
            <Statistic title="Token 使用量" value={status?.agent_stats.token_usage ?? '不可用'} />
          </Col>
        </Row>
        <Text type="secondary">{status?.agent_stats.message || 'Agent 统计口径不可用（服务可能未更新）'}</Text>
      </Card>
    </div>
  );
};

export default SystemPage;
