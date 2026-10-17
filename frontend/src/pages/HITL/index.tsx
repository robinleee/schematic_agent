// HITL approval page
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Modal,
  Input,
  message,
  Typography,
  Statistic,
  Row,
  Col,
  Tabs,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExportOutlined,
  ReloadOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import { hitlApi } from '@/api';
import type { PendingReview, ReviewStatus, DatasheetPendingReview } from '@/types/hitl';
import { apiErrorText } from '@/api/client';

const { Title, Paragraph } = Typography;
const { TextArea } = Input;
const { TabPane } = Tabs;
const errorText = apiErrorText;

const HITLPage: React.FC = () => {
  const [pendingReviews, setPendingReviews] = useState<PendingReview[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [statusFilter] = useState<ReviewStatus | 'all'>('pending');
  const [total, setTotal] = useState(0);
  const [commentModal, setCommentModal] = useState<{
    visible: boolean;
    action: 'approve' | 'reject' | null;
    reviewIds: string[];
  }>({ visible: false, action: null, reviewIds: [] });
  const [comment, setComment] = useState('');

  const loadPendingReviews = useCallback(async () => {
    setLoading(true);
    try {
      const response = await hitlApi.getPending(
        statusFilter === 'all' ? undefined : statusFilter
      );
      setPendingReviews(response.data);
      setTotal(response.total);
    } catch (error) {
      message.error(`加载审批列表失败：${errorText(error)}`);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { void loadPendingReviews(); }, [loadPendingReviews]);

  const handleAction = async (action: 'approve' | 'reject', reviewIds: string[]) => {
    try {
      const response = await hitlApi.reviewAction({
        review_ids: reviewIds,
        action,
        comment: comment || undefined,
      });
      if (response.data.failed) {
        message.warning(`成功 ${response.data.succeeded} 条，失败 ${response.data.failed} 条：${
          response.data.results.filter((item) => !item.success)
            .map((item) => `${item.review_id}: ${item.error}`).join('; ')
        }`);
      } else {
        message.success(`已${action === 'approve' ? '批准' : '拒绝'} ${response.data.succeeded} 条记录`);
      }
      loadPendingReviews();
      setSelectedRowKeys([]);
    } catch (error) {
      message.error(`操作失败：${errorText(error)}`);
    } finally {
      setCommentModal({ visible: false, action: null, reviewIds: [] });
      setComment('');
    }
  };

  const handleExport = async () => {
    try {
      const response = await hitlApi.export();
      message.success(response.data.saved
        ? `已保存 ${response.data.saved} 条规则到服务端 ${response.data.location || '规则文件'}`
        : '没有待保存的已批准规则');
    } catch (error) {
      message.error(`保存规则失败：${errorText(error)}`);
    }
  };

  // --- Datasheet parameter HITL ---
  const [datasheetReviews, setDatasheetReviews] = useState<DatasheetPendingReview[]>([]);
  const [datasheetLoading, setDatasheetLoading] = useState(false);
  const [datasheetSelectedKeys, setDatasheetSelectedKeys] = useState<React.Key[]>([]);
  const [datasheetCommentModal, setDatasheetCommentModal] = useState<{
    visible: boolean;
    action: 'approve' | 'reject' | null;
    reviewIds: string[];
  }>({ visible: false, action: null, reviewIds: [] });
  const [datasheetComment, setDatasheetComment] = useState('');

  const loadDatasheetPending = useCallback(async () => {
    setDatasheetLoading(true);
    try {
      const response = await hitlApi.getDatasheetPending();
      setDatasheetReviews(response.data);
    } catch (error) {
      message.error(`加载 Datasheet 参数审批列表失败：${errorText(error)}`);
    } finally {
      setDatasheetLoading(false);
    }
  }, []);

  useEffect(() => { void loadDatasheetPending(); }, [loadDatasheetPending]);

  const handleDatasheetAction = async (action: 'approve' | 'reject', reviewIds: string[]) => {
    try {
      const response = await hitlApi.datasheetReviewAction({
        review_ids: reviewIds,
        action,
        comment: datasheetComment || undefined,
      });
      if (response.data.failed) {
        message.warning(`成功 ${response.data.succeeded} 条，失败 ${response.data.failed} 条：${
          response.data.results.filter((item) => !item.success)
            .map((item) => `${item.review_id}: ${item.error}`).join('; ')
        }`);
      } else {
        message.success(`已${action === 'approve' ? '批准' : '拒绝'} ${response.data.succeeded} 条参数`);
      }
      void loadDatasheetPending();
      setDatasheetSelectedKeys([]);
    } catch (error) {
      message.error(`操作失败：${errorText(error)}`);
    } finally {
      setDatasheetCommentModal({ visible: false, action: null, reviewIds: [] });
      setDatasheetComment('');
    }
  };

  const handleDatasheetPersist = async () => {
    try {
      const response = await hitlApi.persistDatasheet();
      message.success(response.data.saved
        ? `已保存 ${response.data.saved} 条参数到 amr_data.yaml（并同步写入 Neo4j）`
        : response.data.message || '没有待持久化的已批准参数');
      void loadDatasheetPending();
    } catch (error) {
      message.error(`持久化失败：${errorText(error)}`);
    }
  };

  const datasheetColumns = [
    { title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusText(status)}</Tag>
      ) },
    { title: '器件 (MPN)', dataIndex: 'mpn', key: 'mpn', width: 160, ellipsis: true },
    { title: '参数', dataIndex: 'param_name', key: 'param_name', width: 140 },
    { title: '数值', key: 'value', width: 120,
      render: (_: unknown, record: DatasheetPendingReview) => `${record.value} ${record.unit}` },
    { title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 90,
      render: (v: number) => `${(v * 100).toFixed(0)}%` },
    { title: '来源文件', dataIndex: 'source_file', key: 'source_file', ellipsis: true },
    { title: '审批人', dataIndex: 'reviewer', key: 'reviewer', width: 100,
      render: (text: string) => text || '-' },
    {
      title: '操作', key: 'action', width: 150,
      render: (_: unknown, record: DatasheetPendingReview) => (
        record.status === 'pending' ? (
          <Space>
            <Button type="link" icon={<CheckCircleOutlined />}
              onClick={() => setDatasheetCommentModal({
                visible: true, action: 'approve', reviewIds: [record.review_id],
              })}>批准</Button>
            <Button type="link" danger icon={<CloseCircleOutlined />}
              onClick={() => setDatasheetCommentModal({
                visible: true, action: 'reject', reviewIds: [record.review_id],
              })}>拒绝</Button>
          </Space>
        ) : (
          <span style={{ color: '#999' }}>已处理</span>
        )
      ),
    },
  ];

  const datasheetRowSelection = {
    selectedRowKeys: datasheetSelectedKeys,
    onChange: setDatasheetSelectedKeys,
  };

  const datasheetPendingCount = datasheetReviews.filter((r) => r.status === 'pending').length;
  const datasheetApprovedCount = datasheetReviews.filter((r) => r.status === 'approved').length;
  const datasheetRejectedCount = datasheetReviews.filter((r) => r.status === 'rejected').length;

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending':
        return 'processing';
      case 'approved':
        return 'success';
      case 'rejected':
        return 'error';
      default:
        return 'default';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'pending':
        return '待审批';
      case 'approved':
        return '已批准';
      case 'rejected':
        return '已拒绝';
      default:
        return status;
    }
  };

  const columns = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusText(status)}</Tag>
      ),
    },
    {
      title: '规则',
      dataIndex: 'rule_name',
      key: 'rule_name',
      width: 180,
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
      title: '严重程度',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
    },
    {
      title: '审批人',
      dataIndex: 'reviewer',
      key: 'reviewer',
      width: 100,
      render: (text: string) => text || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: unknown, record: PendingReview) => (
        record.status === 'pending' ? (
          <Space>
            <Button
              type="link"
              icon={<CheckCircleOutlined />}
              onClick={() => {
                setCommentModal({
                  visible: true,
                  action: 'approve',
                  reviewIds: [record.review_id],
                });
              }}
            >
              批准
            </Button>
            <Button
              type="link"
              danger
              icon={<CloseCircleOutlined />}
              onClick={() => {
                setCommentModal({
                  visible: true,
                  action: 'reject',
                  reviewIds: [record.review_id],
                });
              }}
            >
              拒绝
            </Button>
          </Space>
        ) : (
          <span style={{ color: '#999' }}>已处理</span>
        )
      ),
    },
  ];

  const rowSelection = {
    selectedRowKeys,
    onChange: setSelectedRowKeys,
  };

  // Calculate stats
  const pendingCount = pendingReviews.filter((r) => r.status === 'pending').length;
  const approvedCount = pendingReviews.filter((r) => r.status === 'approved').length;
  const rejectedCount = pendingReviews.filter((r) => r.status === 'rejected').length;

  return (
    <div>
      <Title level={4}>HITL 审批</Title>

      <Tabs defaultActiveKey="rules">
        <TabPane tab="审查规则沉淀" key="rules">
          <Card style={{ marginBottom: 16 }}>
            <Row gutter={24}>
              <Col span={6}>
                <Statistic title="待审批" value={pendingCount} />
              </Col>
              <Col span={6}>
                <Statistic title="已批准" value={approvedCount} valueStyle={{ color: '#52c41a' }} />
              </Col>
              <Col span={6}>
                <Statistic title="已拒绝" value={rejectedCount} valueStyle={{ color: '#ff4d4f' }} />
              </Col>
              <Col span={6}>
                <Statistic title="总计" value={total} />
              </Col>
            </Row>
          </Card>

          <Card>
            <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
              <Space>
                <Button
                  icon={<ReloadOutlined />}
                  onClick={loadPendingReviews}
                >
                  刷新
                </Button>
                {selectedRowKeys.length > 0 && (
                  <>
                    <Button
                      type="primary"
                      icon={<CheckCircleOutlined />}
                      onClick={() => {
                        setCommentModal({
                          visible: true,
                          action: 'approve',
                          reviewIds: selectedRowKeys as string[],
                        });
                      }}
                    >
                      批量批准 ({selectedRowKeys.length})
                    </Button>
                    <Button
                      danger
                      icon={<CloseCircleOutlined />}
                      onClick={() => {
                        setCommentModal({
                          visible: true,
                          action: 'reject',
                          reviewIds: selectedRowKeys as string[],
                        });
                      }}
                    >
                      批量拒绝 ({selectedRowKeys.length})
                    </Button>
                  </>
                )}
              </Space>
              <Space>
                <Button icon={<ExportOutlined />} onClick={handleExport}>
                  保存已批准规则
                </Button>
              </Space>
            </div>

            <Table
              columns={columns}
              dataSource={pendingReviews}
              rowKey="review_id"
              loading={loading}
              rowSelection={rowSelection}
              pagination={{ pageSize: 20, total }}
              expandable={{
                expandedRowRender: (record) => (
                  <div>
                    <Paragraph>
                      <strong>期望值:</strong> {record.expected || '-'}
                    </Paragraph>
                    <Paragraph>
                      <strong>实际值:</strong> {record.actual || '-'}
                    </Paragraph>
                    <Paragraph>
                      <strong>建议修复:</strong> {record.suggested_fix || '-'}
                    </Paragraph>
                    {record.review_comment && (
                      <Paragraph>
                        <strong>审批备注:</strong> {record.review_comment}
                      </Paragraph>
                    )}
                  </div>
                ),
              }}
            />
          </Card>
        </TabPane>

        <TabPane tab="Datasheet 参数沉淀" key="datasheet">
          <Card style={{ marginBottom: 16 }}>
            <Row gutter={24}>
              <Col span={6}>
                <Statistic title="待审批" value={datasheetPendingCount} />
              </Col>
              <Col span={6}>
                <Statistic title="已批准" value={datasheetApprovedCount} valueStyle={{ color: '#52c41a' }} />
              </Col>
              <Col span={6}>
                <Statistic title="已拒绝" value={datasheetRejectedCount} valueStyle={{ color: '#ff4d4f' }} />
              </Col>
              <Col span={6}>
                <Statistic title="总计" value={datasheetReviews.length} />
              </Col>
            </Row>
          </Card>

          <Card>
            <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
              <Space>
                <Button icon={<ReloadOutlined />} onClick={loadDatasheetPending}>
                  刷新
                </Button>
                {datasheetSelectedKeys.length > 0 && (
                  <>
                    <Button
                      type="primary"
                      icon={<CheckCircleOutlined />}
                      onClick={() => setDatasheetCommentModal({
                        visible: true, action: 'approve', reviewIds: datasheetSelectedKeys as string[],
                      })}
                    >
                      批量批准 ({datasheetSelectedKeys.length})
                    </Button>
                    <Button
                      danger
                      icon={<CloseCircleOutlined />}
                      onClick={() => setDatasheetCommentModal({
                        visible: true, action: 'reject', reviewIds: datasheetSelectedKeys as string[],
                      })}
                    >
                      批量拒绝 ({datasheetSelectedKeys.length})
                    </Button>
                  </>
                )}
              </Space>
              <Space>
                <Button icon={<SaveOutlined />} onClick={handleDatasheetPersist}>
                  持久化已批准参数
                </Button>
              </Space>
            </div>

            <Table
              columns={datasheetColumns}
              dataSource={datasheetReviews}
              rowKey="review_id"
              loading={datasheetLoading}
              rowSelection={datasheetRowSelection}
              pagination={{ pageSize: 20 }}
              expandable={{
                expandedRowRender: (record) => (
                  <div>
                    <Paragraph><strong>原文片段:</strong> {record.source_text || '-'}</Paragraph>
                    <Paragraph><strong>适用条件:</strong> {record.condition || '-'}</Paragraph>
                    {(record.min_value !== undefined || record.max_value !== undefined) && (
                      <Paragraph>
                        <strong>范围:</strong> {record.min_value ?? '-'} ~ {record.max_value ?? '-'} {record.unit}
                      </Paragraph>
                    )}
                    {record.review_comment && (
                      <Paragraph><strong>审批备注:</strong> {record.review_comment}</Paragraph>
                    )}
                  </div>
                ),
              }}
            />
          </Card>
        </TabPane>
      </Tabs>

      <Modal
        title={commentModal.action === 'approve' ? '批准确认' : '拒绝确认'}
        open={commentModal.visible}
        onOk={() => handleAction(commentModal.action!, commentModal.reviewIds)}
        onCancel={() => {
          setCommentModal({ visible: false, action: null, reviewIds: [] });
          setComment('');
        }}
      >
        <Paragraph>
          确定要{commentModal.action === 'approve' ? '批准' : '拒绝'}{' '}
          {commentModal.reviewIds.length} 条记录吗？
        </Paragraph>
        <TextArea
          placeholder="可选：添加备注"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
        />
      </Modal>

      <Modal
        title={datasheetCommentModal.action === 'approve' ? '批准确认' : '拒绝确认'}
        open={datasheetCommentModal.visible}
        onOk={() => handleDatasheetAction(datasheetCommentModal.action!, datasheetCommentModal.reviewIds)}
        onCancel={() => {
          setDatasheetCommentModal({ visible: false, action: null, reviewIds: [] });
          setDatasheetComment('');
        }}
      >
        <Paragraph>
          确定要{datasheetCommentModal.action === 'approve' ? '批准' : '拒绝'}{' '}
          {datasheetCommentModal.reviewIds.length} 条参数吗？
        </Paragraph>
        <TextArea
          placeholder="可选：添加备注"
          value={datasheetComment}
          onChange={(e) => setDatasheetComment(e.target.value)}
          rows={3}
        />
      </Modal>
    </div>
  );
};

export default HITLPage;
