// Review page
import React, { useState, useEffect } from 'react';
import {
  Card,
  Button,
  Select,
  Table,
  Tag,
  Typography,
  Space,
  Statistic,
  Row,
  Col,
  Switch,
  Spin,
  Empty,
  message,
} from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import { reviewApi } from '@/api';
import { apiErrorText } from '@/api/client';
import { useProjectStore } from '@/stores/useProjectStore';
import type { RuleInfo, Violation, Severity } from '@/types/review';

const { Title, Paragraph } = Typography;

const ReviewPage: React.FC = () => {
  const currentProject = useProjectStore((state) => state.currentProject);
  const [rules, setRules] = useState<RuleInfo[]>([]);
  const [selectedRules, setSelectedRules] = useState<string[]>([]);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [summary, setSummary] = useState<{
    total: number;
    errors: number;
    warnings: number;
    infos: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [enabledOnly, setEnabledOnly] = useState(true);

  useEffect(() => {
    loadRules();
  }, []);

  const loadRules = async () => {
    try {
      const response = await reviewApi.getRules();
      setRules(response.data);
    } catch (error) {
      message.error(`加载规则失败：${apiErrorText(error)}`);
    } finally {
      setRulesLoading(false);
    }
  };

  const runReview = async () => {
    setLoading(true);
    try {
      const response = await reviewApi.runReview({
        rule_ids: selectedRules.length > 0 ? selectedRules : undefined,
        enabled_only: enabledOnly,
        // Backend project_id=None means the shared/aggregate graph; "default"
        // is the frontend's sentinel for that same aggregate view, so it must
        // not be sent as a literal project_id (which would scope to a project
        // actually named "default" instead).
        project_id: currentProject === 'default' ? undefined : currentProject,
      });
      setViolations(response.data.violations);
      setSummary(response.data.summary);
      message.success(`审查完成，发现 ${response.data.summary.total} 个问题`);
    } catch (error) {
      message.error(`审查执行失败：${apiErrorText(error)}`);
    } finally {
      setLoading(false);
    }
  };

  const getSeverityColor = (severity: Severity) => {
    switch (severity) {
      case 'ERROR':
        return 'error';
      case 'WARNING':
        return 'warning';
      case 'INFO':
        return 'info';
      default:
        return 'default';
    }
  };

  const columns = [
    {
      title: '严重程度',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (severity: Severity) => (
        <Tag color={getSeverityColor(severity)}>{severity}</Tag>
      ),
    },
    {
      title: '规则',
      dataIndex: 'rule_name',
      key: 'rule_name',
      width: 200,
      ellipsis: true,
    },
    {
      title: '器件',
      dataIndex: 'refdes',
      key: 'refdes',
      width: 100,
    },
    {
      title: '网络',
      dataIndex: 'net_name',
      key: 'net_name',
      width: 120,
      render: (text: string) => text || '-',
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '期望值',
      dataIndex: 'expected',
      key: 'expected',
      width: 150,
      render: (text: string) => text || '-',
    },
    {
      title: '实际值',
      dataIndex: 'actual',
      key: 'actual',
      width: 150,
      render: (text: string) => text || '-',
    },
  ];

  if (rulesLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 50 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <Title level={4}>原理图审查</Title>

      <Card style={{ marginBottom: 16 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            <Select
              mode="multiple"
              placeholder="选择规则（留空为全部）"
              value={selectedRules}
              onChange={setSelectedRules}
              style={{ minWidth: 300 }}
              options={rules.map((r) => ({ value: r.id, label: r.name }))}
            />
            <span>
              仅启用规则:
              <Switch
                checked={enabledOnly}
                onChange={setEnabledOnly}
                style={{ marginLeft: 8 }}
              />
            </span>
          </Space>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={runReview}
            loading={loading}
          >
            执行审查（项目：{currentProject}）
          </Button>
        </Space>
      </Card>

      {summary && (
        <Card style={{ marginBottom: 16 }}>
          <Row gutter={24}>
            <Col span={6}>
              <Statistic title="总计" value={summary.total} />
            </Col>
            <Col span={6}>
              <Statistic title="错误" value={summary.errors} valueStyle={{ color: '#cf1322' }} />
            </Col>
            <Col span={6}>
              <Statistic title="警告" value={summary.warnings} valueStyle={{ color: '#fa8c16' }} />
            </Col>
            <Col span={6}>
              <Statistic title="信息" value={summary.infos} valueStyle={{ color: '#1890ff' }} />
            </Col>
          </Row>
        </Card>
      )}

      <Card title="违规列表">
        {violations.length > 0 ? (
          <Table
            columns={columns}
            dataSource={violations}
            rowKey={(record) => `${record.rule_id}-${record.refdes}`}
            pagination={{ pageSize: 10 }}
            expandable={{
              expandedRowRender: (record) => (
                <div>
                  <Paragraph>
                    <strong>建议修复:</strong> {record.suggested_fix || '无'}
                  </Paragraph>
                </div>
              ),
            }}
          />
        ) : (
          <Empty description="点击「执行审查」开始审查" />
        )}
      </Card>
    </div>
  );
};

export default ReviewPage;
