// System status page
import React, { useState, useEffect } from 'react';
import { Typography, Button, Spin, Alert, Tooltip } from 'antd';
import { ReloadOutlined, WarningOutlined } from '@ant-design/icons';
import { systemApi } from '@/api';
import { apiErrorText } from '@/api/client';
import type { SystemStatus, ServiceStatusType } from '@/types/system';
import PageHeader from '@/components/common/PageHeader';

const { Text } = Typography;

const STATUS_META: Record<ServiceStatusType, { label: string; tone: 'ok' | 'warn' | 'error' | 'off' }> = {
  running: { label: '运行中', tone: 'ok' },
  stopped: { label: '已停止', tone: 'warn' },
  degraded: { label: '降级', tone: 'warn' },
  error: { label: '错误', tone: 'error' },
};

const LATENCY_WARN_MS = 5000;

const SystemPage: React.FC = () => {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorText, setErrorText] = useState('');

  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const formatNumber = (value: number | null | undefined) =>
    value == null ? '—' : value.toLocaleString('en-US');

  // 大数字换成秒，避免 "89580.1 ms" 这种难读的写法
  const formatLatency = (ms: number | null | undefined) => {
    if (ms == null) return null;
    if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s`;
    return `${Math.round(ms)} ms`;
  };

  if (loading && !status) {
    return (
      <div className="page">
        <PageHeader title="系统状态" description="服务健康、数据规模与 Agent 调用指标。" />
        <div className="surface" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
          <Spin size="large" />
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        title="系统状态"
        description="服务健康、图谱数据规模与 Agent 调用指标；数值为接口实时返回。"
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadStatus} loading={loading}>
            刷新
          </Button>
        }
      />

      {errorText && (
        <Alert type="error" showIcon message="系统状态获取失败" description={errorText} />
      )}

      <section className="surface">
        <div className="surface-head">
          <span className="surface-title">服务状态</span>
          <span className="surface-sub">
            {status ? `${status.services.length} 个依赖服务` : '暂无数据'}
          </span>
        </div>
        <div className="metric-grid">
          {(status?.services ?? []).map((service) => {
            const meta = STATUS_META[service.status] ?? {
              label: service.status,
              tone: 'off' as const,
            };
            const slow = service.latency_ms != null && service.latency_ms > LATENCY_WARN_MS;
            return (
              <div className="metric-card" key={service.name}>
                <div className="metric-label">
                  <i className="hx-dot" data-state={meta.tone === 'ok' ? 'ok' : meta.tone === 'warn' ? 'warn' : 'off'} />
                  <span style={{ color: 'var(--hx-text-2)', fontWeight: 500 }}>{service.name}</span>
                </div>
                <div className="metric-value" data-tone={slow ? 'error' : undefined}>
                  {formatLatency(service.latency_ms) ?? meta.label}
                  {slow && <WarningOutlined style={{ fontSize: 14, marginLeft: 6 }} />}
                </div>
                <div className="metric-meta">
                  {meta.label}
                  {service.version ? ` · v${service.version}` : ''}
                  {service.message && (
                    <Tooltip title={service.message}>
                      <div style={{ marginTop: 2 }}>{service.message}</div>
                    </Tooltip>
                  )}
                </div>
              </div>
            );
          })}
          {!status?.services?.length && (
            <div className="empty-state" style={{ minHeight: 80 }}>
              <span className="empty-state-text">没有可用的服务状态</span>
            </div>
          )}
        </div>
      </section>

      <section className="surface">
        <div className="surface-head">
          <span className="surface-title">数据统计</span>
          <span className="surface-sub">
            {status?.data_stats.status === 'available' ? '图谱数据可用' : '图谱数据不可用'}
          </span>
        </div>
        <div className="metric-grid">
          <div className="metric-card">
            <div className="metric-label">器件数量</div>
            <div className="metric-value" data-tone={status?.data_stats.components == null ? 'muted' : undefined}>
              {formatNumber(status?.data_stats.components)}
            </div>
            <div className="metric-meta">Neo4j Component 节点</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">引脚数量</div>
            <div className="metric-value" data-tone={status?.data_stats.pins == null ? 'muted' : undefined}>
              {formatNumber(status?.data_stats.pins)}
            </div>
            <div className="metric-meta">Pin 节点</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">网络数量</div>
            <div className="metric-value" data-tone={status?.data_stats.nets == null ? 'muted' : undefined}>
              {formatNumber(status?.data_stats.nets)}
            </div>
            <div className="metric-meta">Net 节点</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">PartType 覆盖率</div>
            <div className="metric-value" data-tone={status?.data_stats.part_type_coverage == null ? 'muted' : undefined}>
              {status?.data_stats.part_type_coverage == null
                ? '—'
                : `${status.data_stats.part_type_coverage}%`}
            </div>
            <div className="metric-meta">器件类型归一化覆盖比例</div>
          </div>
        </div>
      </section>

      <section className="surface">
        <div className="surface-head">
          <span className="surface-title">Agent 统计</span>
          <span className="surface-sub">本进程累计</span>
        </div>
        <div className="metric-grid">
          <div className="metric-card">
            <div className="metric-label">REST / WS 查询次数</div>
            <div className="metric-value">{formatNumber(status?.agent_stats.query_count)}</div>
            <div className="metric-meta">进程启动以来</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">成功 / 失败</div>
            <div className="metric-value">
              {status ? (
                <>
                  <span style={{ color: 'var(--hx-success)' }}>{status.agent_stats.success_count}</span>
                  <span style={{ color: 'var(--hx-text-3)', margin: '0 4px', fontSize: 18 }}>/</span>
                  <span style={{ color: 'var(--hx-error)' }}>{status.agent_stats.failure_count}</span>
                </>
              ) : (
                '—'
              )}
            </div>
            <div className="metric-meta">调用成败计数</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">平均耗时</div>
            <div
              className="metric-value"
              data-tone={
                status?.agent_stats.average_duration_ms == null
                  ? 'muted'
                  : status.agent_stats.average_duration_ms > LATENCY_WARN_MS
                    ? 'error'
                    : undefined
              }
            >
              {formatLatency(status?.agent_stats.average_duration_ms) ?? '—'}
            </div>
            <div className="metric-meta">&gt; {LATENCY_WARN_MS} ms 判为偏慢</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Token 使用量</div>
            <div className="metric-value" data-tone={status?.agent_stats.token_usage == null ? 'muted' : undefined}>
              {formatNumber(status?.agent_stats.token_usage)}
            </div>
            <div className="metric-meta">模型调用累计</div>
          </div>
        </div>
        <Tooltip title={status?.agent_stats.message || 'Agent 统计口径不可用（服务可能未更新）'}>
          <Text className="hx-muted" style={{ display: 'block', marginTop: 12 }}>
            统计口径：仅统计当前进程内的 REST / WS 对话；Token 用量与跨进程历史暂不可用。
          </Text>
        </Tooltip>
      </section>
    </div>
  );
};

export default SystemPage;
