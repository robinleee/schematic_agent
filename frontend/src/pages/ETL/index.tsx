// ETL import page
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Upload,
  Button,
  Select,
  message,
  Typography,
  Space,
  Modal,
  Input,
  Alert,
  Descriptions,
} from 'antd';
import type { UploadFile } from 'antd/es/upload/interface';
import {
  UploadOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  DeleteOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { etlApi } from '@/api';
import { apiErrorText } from '@/api/client';
import { useProjectStore } from '@/stores/useProjectStore';
import type { ETLPreviewResult, ETLResult } from '@/types/etl';
import PageHeader from '@/components/common/PageHeader';

const { Paragraph, Text } = Typography;

const ETLPage: React.FC = () => {
  const { projects, setProjects, currentProject, setCurrentProject } = useProjectStore();
  const [errorText, setErrorText] = useState('');
  const [progressError, setProgressError] = useState('');
  const [files, setFiles] = useState<{
    pstxnet?: File;
    pstxprt?: File;
    pstchip?: File;
    bom?: File;
  }>({});
  const [preview, setPreview] = useState<ETLPreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [result, setResult] = useState<ETLResult | null>(null);
  const [jobId, setJobId] = useState('');
  const [jobStatus, setJobStatus] = useState('');
  const [createModal, setCreateModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');

  const loadProjects = useCallback(async () => {
    try {
      const response = await etlApi.getProjects();
      setProjects(response.data);
      if (!response.data.includes(currentProject)) setCurrentProject(response.data.includes('default') ? 'default' : response.data[0] || 'default');
    } catch (error) {
      setErrorText(`加载项目列表失败：${apiErrorText(error)}`);
    }
  }, [currentProject, setCurrentProject, setProjects]);

  useEffect(() => { void loadProjects(); }, [loadProjects]);

  useEffect(() => {
    if (!jobId || !['queued', 'running'].includes(jobStatus)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const progress = await etlApi.getProgress(jobId);
        if (!active) return;
        setJobStatus(progress.status);
        setProgressError(`${progress.status}: ${progress.progress}% — ${progress.error || progress.result?.message || progress.message}`);
        if (progress.result) setResult(progress.result);
        if (progress.status === 'succeeded' && progress.result?.success) message.success('ETL 导入成功');
        if (['failed', 'cancelled', 'timeout'].includes(progress.status)) {
          setErrorText(progress.error || progress.result?.message || progress.message);
        }
      } catch (error) {
        if (active) {
          setJobStatus('poll_error');
          setProgressError(`进度查询失败：${apiErrorText(error)}；请使用 job_id 重试`);
        }
      }
    }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [jobId, jobStatus]);

  const handlePreview = async () => {
    if (!files.pstxnet || !files.pstxprt || !files.pstchip) {
      message.error('请上传必需的文件');
      return;
    }

    setPreviewLoading(true);
    setPreview(null);
    setResult(null);
    setJobId('');
    setJobStatus('');
    setErrorText('');
    try {
      const response = await etlApi.preview(
        files.pstxnet,
        files.pstxprt,
        files.pstchip,
        files.bom
      );
      if (!response.success || !response.data.success) throw new Error(response.message || '预览失败，请检查输入文件');
      setPreview(response.data);
    } catch (error) {
      setErrorText(`预览失败：${apiErrorText(error)}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleImport = async () => {
    if (!files.pstxnet || !files.pstxprt || !files.pstchip) {
      message.error('请上传必需的文件');
      return;
    }

    setLoading(true);
    setResult(null);
    setErrorText('');
    try {
      const response = await etlApi.run(
        files.pstxnet,
        files.pstxprt,
        files.pstchip,
        currentProject,
        files.bom
      );
      if (!response.success || !response.job_id) throw new Error(response.message || '无法启动 ETL');
      setJobId(response.job_id);
      setJobStatus(response.status);
      setProgressError(`任务已提交：${response.job_id}`);
    } catch (error) {
      setErrorText(`ETL 导入失败：${apiErrorText(error)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateProject = async () => {
    if (!newProjectName) {
      message.error('请输入项目名称');
      return;
    }

    try {
      const response = await etlApi.createProject(newProjectName.trim());
      if (!response.success) throw new Error(response.message || '创建失败');
      message.success('项目创建成功');
      setCreateModal(false);
      setCurrentProject(newProjectName.trim());
      setNewProjectName('');
      await loadProjects();
    } catch (error) {
      setErrorText(`项目创建失败：${apiErrorText(error)}`);
    }
  };

  const handleDeleteProject = async () => {
    if (currentProject === 'default') {
      message.error('不能删除默认项目');
      return;
    }

    try {
      const response = await etlApi.deleteProject(currentProject);
      if (!response.success) throw new Error(response.message || '删除失败');
      message.success('项目删除成功');
      setCurrentProject('default');
      await loadProjects();
    } catch (error) {
      setErrorText(`项目删除失败：${apiErrorText(error)}`);
    }
  };

  const fileUploadProps = (fileType: keyof typeof files) => ({
    beforeUpload: (file: File) => {
      setFiles((prev) => ({ ...prev, [fileType]: file }));
      return false;
    },
    onRemove: () => {
      setFiles((prev) => {
        const newFiles = { ...prev };
        delete newFiles[fileType];
        return newFiles;
      });
    },
    fileList: files[fileType] ? [{ uid: fileType, name: files[fileType]!.name } as UploadFile] : [],
  });

  return (
    <div className="page">
      <PageHeader
        title="ETL 导入"
        description="上传 PSTX 网表并解析为器件-引脚-网络图谱；导入为异步任务，仅成功终态代表完成。"
      />

      {errorText && <Alert type="error" showIcon message={errorText} />}
      <Alert
        type="info"
        showIcon
        message={`任务 ID：${jobId || '尚未提交'}。进度百分比是阶段指示，不代表数据已可查。`}
      />

      <section className="surface">
        <div className="toolbar">
          <div className="field" style={{ flex: '0 1 260px' }}>
            <span className="field-label">当前项目</span>
            <Select
              value={currentProject}
              onChange={setCurrentProject}
              options={projects.map((p) => ({ value: p, label: p }))}
            />
          </div>
          <Button icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>
            新建项目
          </Button>
          <Button
            icon={<DeleteOutlined />}
            danger
            onClick={() => Modal.confirm({
              title: `确认删除项目 ${currentProject}？`,
              content: '此操作会删除项目数据，无法撤销。',
              okText: '删除', okType: 'danger', onOk: handleDeleteProject,
            })}
            disabled={currentProject === 'default'}
          >
            删除项目
          </Button>
        </div>
      </section>

      <section className="surface">
        <div className="surface-head">
          <span className="surface-title">文件上传</span>
          <span className="surface-sub">pstxnet / pstxprt / pstchip 必需，BOM 可选</span>
        </div>

        <div className="hx-upload-grid">
          <div className="field">
            <span className="field-label">网表文件 · 必需</span>
            <Upload {...fileUploadProps('pstxnet')}>
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </div>
          <div className="field">
            <span className="field-label">器件文件 · 必需</span>
            <Upload {...fileUploadProps('pstxprt')}>
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </div>
          <div className="field">
            <span className="field-label">芯片库文件 · 必需</span>
            <Upload {...fileUploadProps('pstchip')}>
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </div>
          <div className="field">
            <span className="field-label">BOM 文件 · 可选</span>
            <Upload {...fileUploadProps('bom')}>
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </div>
        </div>

        <div className="toolbar" style={{ marginTop: 16 }}>
          <div className="toolbar-spacer" />
          <Button
            icon={<EyeOutlined />}
            onClick={handlePreview}
            loading={previewLoading}
          >
            预览
          </Button>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => Modal.confirm({
              title: `确认导入到 ${currentProject}？`,
              content: '导入可能替换目标项目现有数据，请先确认备份及预览结果。',
              okText: '确认导入', onOk: handleImport,
            })}
            loading={loading}
          >
            执行导入
          </Button>
        </div>
      </section>

      {preview && (
        <section className="surface">
          <div className="surface-head">
            <span className="surface-title">预览结果</span>
            <span className="surface-sub">仅解析统计，未写入图谱</span>
          </div>
          <div className="metric-grid">
            <div className="metric-card">
              <div className="metric-label">器件数量</div>
              <div className="metric-value">{preview.components_count ?? '—'}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">拓扑数量</div>
              <div className="metric-value">{preview.topology_count ?? '—'}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">唯一网络</div>
              <div className="metric-value">{preview.unique_nets ?? '—'}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">PartType 覆盖率</div>
              <div className="metric-value">
                {preview.parttype_coverage == null ? '—' : `${preview.parttype_coverage}%`}
              </div>
            </div>
          </div>
          {preview.bom_enriched_components != null && (
            <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
              BOM 关联器件：<Text strong>{preview.bom_enriched_components}</Text>
            </Paragraph>
          )}
          {preview.bom_issues.length > 0 && (
            <Paragraph type="warning" style={{ marginTop: 12, marginBottom: 0 }}>
              BOM 问题 ({preview.bom_issues.length} 条)：
              {preview.bom_issues.map((issue, i) => (
                <div key={i}>{Object.entries(issue).map(([k, v]) => `${k}: ${v}`).join('，')}</div>
              ))}
            </Paragraph>
          )}
          <Descriptions size="small" column={2} style={{ marginTop: 16 }}>
            <Descriptions.Item label="电源网络">{preview.power_nets_count ?? '不可用'}</Descriptions.Item>
            <Descriptions.Item label="地网络">{preview.ground_nets_count ?? '不可用'}</Descriptions.Item>
            <Descriptions.Item label="类型分布">{Object.entries(preview.parttype_distribution).map(([key, value]) => `${key}: ${value}`).join('；') || '暂无数据'}</Descriptions.Item>
            <Descriptions.Item label="主要网络">{preview.top_nets.join('；') || '暂无数据'}</Descriptions.Item>
          </Descriptions>
        </section>
      )}

      {result && (
        <section className="surface">
          <div className="surface-head">
            <span className="surface-title">导入结果</span>
            <span className="surface-sub">{result.quality_passed ? '质量检查通过' : '质量检查未通过'}</span>
          </div>
          <div className="metric-grid">
            <div className="metric-card">
              <div className="metric-label">器件数量</div>
              <div className="metric-value">{result.components_count ?? '—'}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">拓扑数量</div>
              <div className="metric-value">{result.topology_count ?? '—'}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">PartType 覆盖率</div>
              <div className="metric-value">
                {result.parttype_coverage == null ? '—' : `${result.parttype_coverage}%`}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">质量检查</div>
              <div className="metric-value" data-tone={result.quality_passed ? 'success' : 'error'}>
                {result.quality_passed ? '通过' : '未通过'}
              </div>
            </div>
          </div>
          <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>{result.message}</Paragraph>
          {result.bom_issues.length > 0 && (
            <Paragraph type="warning" style={{ marginTop: 12, marginBottom: 0 }}>
              BOM 问题 ({result.bom_issues.length} 条)：
              {result.bom_issues.map((issue, i) => (
                <div key={i}>{Object.entries(issue).map(([k, v]) => `${k}: ${v}`).join('，')}</div>
              ))}
            </Paragraph>
          )}
          {result.quality_report && (
            <Card size="small" title="质量报告" style={{ marginTop: 16 }}>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="状态">{result.quality_report.passed ? '通过' : '未通过'}</Descriptions.Item>
                <Descriptions.Item label="器件">{result.quality_report.components ?? '不可用'}</Descriptions.Item>
                <Descriptions.Item label="引脚">{result.quality_report.pins ?? '不可用'}</Descriptions.Item>
                <Descriptions.Item label="网络">{result.quality_report.nets ?? '不可用'}</Descriptions.Item>
                <Descriptions.Item label="PartType 覆盖率">{result.quality_report.part_type_coverage ?? '不可用'}</Descriptions.Item>
              </Descriptions>
              {result.quality_report.details && <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>{JSON.stringify(result.quality_report.details, null, 2)}</pre>}
            </Card>
          )}
        </section>
      )}

      <section className="surface">
        <div className="surface-head">
          <span className="surface-title">查询任务状态</span>
          <span className="surface-sub">{progressError || '输入 job_id 查询异步任务'}</span>
        </div>
        <Space>
          <Input.Search placeholder="输入 job_id" enterButton="查询" onSearch={async (jobId) => {
            if (!jobId.trim()) return;
            try {
              const progress = await etlApi.getProgress(jobId.trim());
              setProgressError(`${progress.status}: ${progress.progress}% — ${progress.error || progress.result?.message || progress.message}`);
              setErrorText(['failed', 'cancelled', 'timeout'].includes(progress.status)
                ? progress.error || progress.result?.message || progress.message : '');
              setJobId(progress.job_id);
              setJobStatus(progress.status);
              setResult(progress.result);
            } catch (error) {
              setProgressError(`进度不可用：${apiErrorText(error)}`);
            }
          }} />
        </Space>
      </section>

      <Modal
        title="新建项目"
        open={createModal}
        onOk={handleCreateProject}
        onCancel={() => setCreateModal(false)}
      >
        <Input
          placeholder="输入项目名称"
          value={newProjectName}
          onChange={(e) => setNewProjectName(e.target.value)}
        />
      </Modal>
    </div>
  );
};

export default ETLPage;
