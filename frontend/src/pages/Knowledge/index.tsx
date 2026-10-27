// Knowledge management page
import React, { useState, useEffect } from 'react';
import {
  Card,
  Tabs,
  Upload,
  Button,
  Input,
  Select,
  message,
  Typography,
  Tag,
  Space,
} from 'antd';
import {
  UploadOutlined,
  SearchOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { knowledgeApi } from '@/api';
import { apiErrorText } from '@/api/client';
import type { SearchResult, KnowledgeStats } from '@/types/knowledge';
import { useProjectStore } from '@/stores/useProjectStore';
import PageHeader from '@/components/common/PageHeader';

const { Paragraph, Text } = Typography;
const { Dragger } = Upload;

const KnowledgePage: React.FC = () => {
  const currentProject = useProjectStore((state) => state.currentProject);
  const [uploading, setUploading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [mpn, setMpn] = useState('');
  const [category, setCategory] = useState('general');
  const [searchMpn, setSearchMpn] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [statsError, setStatsError] = useState('');
  const loadStats = async () => {
    try {
      const response = await knowledgeApi.getStats();
      setStats(response.data);
      setStatsError('');
    } catch (error) {
      setStatsError(apiErrorText(error));
      setStats(null);
    }
  };
  useEffect(() => { void loadStats(); }, []);

  const handleUpload = async (file: File) => {
    if (!mpn) {
      message.error('请输入器件型号 (MPN)');
      return false;
    }
    
    setUploading(true);
    try {
      // Backend project_id=None means the shared/aggregate graph; "default"
      // is the frontend's sentinel for that same aggregate view, so it must
      // not be sent as a literal project_id (which would scope to a project
      // actually named "default" instead).
      const response = await knowledgeApi.upload(
        file, mpn, category, currentProject === 'default' ? undefined : currentProject
      );
      if (!response.success) throw new Error(response.message || '上传失败');
      message.success(`成功导入 ${response.data.chunk_count} 个知识切片`);
      void loadStats();
    } catch (error) {
      message.error(`上传失败：${apiErrorText(error)}`);
    } finally {
      setUploading(false);
    }
    return false;
  };

  const handleSearch = async () => {
    if (!searchQuery) {
      message.error('请输入查询内容');
      return;
    }
    
    setSearching(true);
    try {
      const response = await knowledgeApi.search({
        mpn: searchMpn || undefined,
        query: searchQuery,
        max_results: 5,
        project_id: currentProject === 'default' ? undefined : currentProject,
      });
      if (!response.success) throw new Error(response.message || '查询失败');
      setSearchResult(response.data);
    } catch (error) {
      setSearchResult(null);
      message.error(`查询失败：${apiErrorText(error)}`);
    } finally {
      setSearching(false);
    }
  };

  const uploadProps = {
    name: 'file',
    accept: '.pdf,.txt',
    beforeUpload: handleUpload,
    showUploadList: false,
  };

  return (
    <div className="page">
      <PageHeader
        title="知识库"
        description="Datasheet 与应用笔记按器件型号（MPN）归档，供对话与审查按 Tier 分层检索。"
        extra={<Tag bordered={false} className="hx-project-tag">{currentProject}</Tag>}
      />

      <section className="surface hx-tabs-surface">
        <Tabs defaultActiveKey="upload" items={[
          {
            key: 'upload',
            label: (
              <span>
                <UploadOutlined /> 文档上传
              </span>
            ),
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div className="toolbar">
                  <div className="field" style={{ flex: '1 1 260px', maxWidth: 360 }}>
                    <span className="field-label">器件型号 (MPN)</span>
                    <Input
                      placeholder="例如：MT25QU256ABA8E12"
                      value={mpn}
                      onChange={(e) => setMpn(e.target.value)}
                    />
                  </div>
                  <div className="field" style={{ flex: '1 1 200px', maxWidth: 240 }}>
                    <span className="field-label">分类</span>
                    <Select
                      value={category}
                      onChange={setCategory}
                      options={[
                        { value: 'datasheet', label: '数据手册' },
                        { value: 'design_guide', label: '设计指南' },
                        { value: 'application_note', label: '应用笔记' },
                        { value: 'general', label: '通用知识' },
                      ]}
                    />
                  </div>
                </div>

                <Dragger {...uploadProps} disabled={uploading}>
                  <p className="ant-upload-drag-icon">
                    <FileTextOutlined />
                  </p>
                  <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
                  <p className="ant-upload-hint">支持 PDF、TXT 格式，上传后自动切片入库</p>
                </Dragger>
              </div>
            ),
          },
          {
            key: 'search',
            label: (
              <span>
                <SearchOutlined /> 知识检索测试
              </span>
            ),
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div className="toolbar">
                  <div className="field" style={{ flex: '0 1 240px' }}>
                    <span className="field-label">器件型号（可选）</span>
                    <Input
                      placeholder="例如：MT25QU256ABA8E12"
                      value={searchMpn}
                      onChange={(e) => setSearchMpn(e.target.value)}
                    />
                  </div>
                  <div className="field" style={{ flex: '1 1 320px' }}>
                    <span className="field-label">查询内容</span>
                    <Input
                      placeholder="输入查询内容"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onPressEnter={handleSearch}
                    />
                  </div>
                  <Button
                    type="primary"
                    icon={<SearchOutlined />}
                    onClick={handleSearch}
                    loading={searching}
                  >
                    搜索
                  </Button>
                </div>

                {searchResult ? (
                  <Card size="small" title="检索结果">
                    <Paragraph>
                      <Tag color="blue">{searchResult.tier}</Tag>
                      <Tag>状态: {searchResult.status}</Tag>
                      <Tag>置信度: {(searchResult.confidence * 100).toFixed(0)}%</Tag>
                      {searchResult.source && <Tag>来源: {searchResult.source}</Tag>}
                    </Paragraph>
                    <Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto', margin: 0 }}>
                      {searchResult.content || '未找到匹配内容'}
                    </Paragraph>
                  </Card>
                ) : (
                  <div className="empty-state">
                    <div className="empty-state-icon"><SearchOutlined /></div>
                    <div className="empty-state-text">输入查询内容进行检索测试</div>
                  </div>
                )}
              </div>
            ),
          },
          {
            key: 'stats',
            label: (
              <span>
                <DatabaseOutlined /> 知识库统计
              </span>
            ),
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div className="toolbar">
                  <div className="toolbar-spacer" />
                  <Button icon={<ReloadOutlined />} onClick={loadStats}>
                    刷新统计
                  </Button>
                </div>
                {statsError && <Paragraph type="danger" style={{ margin: 0 }}>统计不可用：{statsError}</Paragraph>}
                <div className="metric-grid">
                  <div className="metric-card">
                    <div className="metric-label">Tier1 切片数</div>
                    <div className="metric-value" data-tone={stats?.tier1_chunks == null ? 'muted' : undefined}>
                      {stats?.tier1_chunks == null ? '—' : stats.tier1_chunks.toLocaleString('en-US')}
                    </div>
                    <div className="metric-meta">向量库切片总量</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Tier2 启用</div>
                    <div className="metric-value">{stats ? (stats.tier2_enabled ? '是' : '否') : '—'}</div>
                    <div className="metric-meta">精排检索层</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Tier3 启用</div>
                    <div className="metric-value">{stats ? (stats.tier3_enabled ? '是' : '否') : '—'}</div>
                    <div className="metric-meta">图谱增强层</div>
                  </div>
                </div>
                <Space direction="vertical" size={4}>
                  <Text className="hx-muted">来源分布</Text>
                  <Text>
                    {stats
                      ? Object.entries(stats.source_distribution)
                          .map(([source, count]) => `${source}: ${count}`)
                          .join('；') || '暂无数据'
                      : '暂无数据'}
                  </Text>
                </Space>
              </div>
            ),
          },
        ]} />
      </section>
    </div>
  );
};

export default KnowledgePage;
