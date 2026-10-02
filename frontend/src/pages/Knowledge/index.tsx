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
  Space,
  Statistic,
  Row,
  Col,
  Empty,
  Tag,
} from 'antd';
import {
  UploadOutlined,
  SearchOutlined,
  DatabaseOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { knowledgeApi } from '@/api';
import { apiErrorText } from '@/api/client';
import type { SearchResult, KnowledgeStats } from '@/types/knowledge';
import { useProjectStore } from '@/stores/useProjectStore';

const { Title, Paragraph, Text } = Typography;
const { Dragger } = Upload;
const { TabPane } = Tabs;

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
      const response = await knowledgeApi.upload(file, mpn, category, currentProject);
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
        project_id: currentProject,
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
    <div>
      <Title level={4}>知识库管理</Title>

      <Tabs defaultActiveKey="upload">
        <TabPane tab="文档上传" key="upload" icon={<UploadOutlined />}>
          <Card>
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <Row gutter={16}>
                <Col span={8}>
                  <Text>器件型号 (MPN):</Text>
                  <Input
                    placeholder="例如: MT25QU256ABA8E12"
                    value={mpn}
                    onChange={(e) => setMpn(e.target.value)}
                    style={{ marginTop: 8 }}
                  />
                </Col>
                <Col span={8}>
                  <Text>分类:</Text>
                  <Select
                    value={category}
                    onChange={setCategory}
                    style={{ width: '100%', marginTop: 8 }}
                    options={[
                      { value: 'datasheet', label: '数据手册' },
                      { value: 'design_guide', label: '设计指南' },
                      { value: 'application_note', label: '应用笔记' },
                      { value: 'general', label: '通用知识' },
                    ]}
                  />
                </Col>
              </Row>

              <Dragger {...uploadProps} disabled={uploading}>
                <p className="ant-upload-drag-icon">
                  <FileTextOutlined />
                </p>
                <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
                <p className="ant-upload-hint">支持 PDF、TXT 格式</p>
              </Dragger>
            </Space>
          </Card>
        </TabPane>

        <TabPane tab="知识检索测试" key="search" icon={<SearchOutlined />}>
          <Card>
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <Row gutter={16}>
                <Col span={8}>
                  <Text>器件型号 (可选):</Text>
                  <Input
                    placeholder="例如: MT25QU256ABA8E12"
                    value={searchMpn}
                    onChange={(e) => setSearchMpn(e.target.value)}
                    style={{ marginTop: 8 }}
                  />
                </Col>
                <Col span={12}>
                  <Text>查询内容:</Text>
                  <Input
                    placeholder="输入查询内容"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    style={{ marginTop: 8 }}
                  />
                </Col>
                <Col span={4}>
                  <Button
                    type="primary"
                    icon={<SearchOutlined />}
                    onClick={handleSearch}
                    loading={searching}
                    style={{ marginTop: 28 }}
                  >
                    搜索
                  </Button>
                </Col>
              </Row>

              {searchResult ? (
                <Card size="small" title="检索结果">
                  <Paragraph>
                    <Tag color="blue">{searchResult.tier}</Tag>
                    <Tag>状态: {searchResult.status}</Tag>
                    <Tag>置信度: {(searchResult.confidence * 100).toFixed(0)}%</Tag>
                    {searchResult.source && <Tag>来源: {searchResult.source}</Tag>}
                  </Paragraph>
                  <Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                    {searchResult.content || '未找到匹配内容'}
                  </Paragraph>
                </Card>
              ) : (
                <Empty description="输入查询内容进行检索测试" />
              )}
            </Space>
          </Card>
        </TabPane>

        <TabPane tab="知识库统计" key="stats" icon={<DatabaseOutlined />}>
          <Card>
            <Button onClick={loadStats} style={{ marginBottom: 12 }}>刷新统计</Button>
            {statsError && <Paragraph type="danger">统计不可用：{statsError}</Paragraph>}
            <Row gutter={24}>
              <Col span={8}>
                <Statistic title="Tier1 切片数" value={stats?.tier1_chunks ?? '不可用'} />
              </Col>
              <Col span={8}>
                <Statistic title="Tier2 启用" value={stats ? (stats.tier2_enabled ? '是' : '否') : '不可用'} />
              </Col>
              <Col span={8}>
                <Statistic title="Tier3 启用" value={stats ? (stats.tier3_enabled ? '是' : '否') : '不可用'} />
              </Col>
            </Row>
            {stats && <Paragraph>来源分布：{Object.entries(stats.source_distribution).map(([source, count]) => `${source}: ${count}`).join('；') || '暂无数据'}</Paragraph>}
          </Card>
        </TabPane>
      </Tabs>
    </div>
  );
};

export default KnowledgePage;
