// Review page
import React, { useState, useEffect } from 'react';
import {
  Button,
  Select,
  Table,
  Tag,
  Typography,
  Switch,
  Spin,
  message,
} from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import { reviewApi } from '@/api';
import { apiErrorText } from '@/api/client';
import { useProjectStore } from '@/stores/useProjectStore';
import type { RuleInfo, Violation, Severity } from '@/types/review';
import PageHeader from '@/components/common/PageHeader';

const { Paragraph } = Typography;

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
      <div className="page">
        <PageHeader title="原理图审查" description="按规则库对当前项目图谱执行设计检查。" />
        <div className="surface" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
          <Spin size="large" />
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        title="原理图审查"
        description={`按规则库对项目「${currentProject}」的器件-网络图谱执行设计检查，结果按严重程度归类。`}
      />

      <section className="surface">
        <div className="toolbar">
          <div className="field" style={{ flex: '1 1 320px', maxWidth: 520 }}>
            <span className="field-label">检查规则（留空为全部）</span>
            <Select
              mode="multiple"
              placeholder="选择规则"
              value={selectedRules}
              onChange={setSelectedRules}
              maxTagCount="responsive"
              options={rules.map((r) => ({ value: r.id, label: r.name }))}
            />
          </div>
          <div className="field">
            <span className="field-label">仅启用规则</span>
            <Switch checked={enabledOnly} onChange={setEnabledOnly} />
          </div>
          <div className="toolbar-spacer" />
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={runReview}
            loading={loading}
          >
            执行审查
          </Button>
        </div>
      </section>

      {summary && (
        <div className="hx-summary-grid">
          <div className="metric-card">
            <div className="metric-label">总计</div>
            <div className="metric-value">{summary.total}</div>
            <div className="metric-meta">本轮全部违规项</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">错误</div>
            <div className="metric-value" data-tone="error">{summary.errors}</div>
            <div className="metric-meta">必须修复</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">警告</div>
            <div className="metric-value" data-tone="warning">{summary.warnings}</div>
            <div className="metric-meta">建议复核</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">信息</div>
            <div className="metric-value">{summary.infos}</div>
            <div className="metric-meta">提示项</div>
          </div>
        </div>
      )}

      <section className="surface">
        <div className="surface-head">
          <span className="surface-title">违规列表</span>
          <span className="surface-sub">{violations.length} 条</span>
        </div>
        {violations.length > 0 ? (
          <Table
            columns={columns}
            dataSource={violations}
            rowKey={(record) => `${record.rule_id}-${record.refdes}`}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            expandable={{
              expandedRowRender: (record) => (
                <div>
                  <Paragraph style={{ margin: 0 }}>
                    <strong>建议修复:</strong> {record.suggested_fix || '无'}
                  </Paragraph>
                </div>
              ),
            }}
          />
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon"><PlayCircleOutlined /></div>
            <div className="empty-state-text">点击「执行审查」开始检查当前项目</div>
          </div>
        )}
      </section>
    </div>
  );
};

export default ReviewPage;
