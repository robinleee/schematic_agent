// Header：面包屑式页面标题 + 副标题 / 引擎状态 / 主题开关 / 项目 Tag
import React, { useEffect, useState } from 'react';
import { Button, Tag, Tooltip } from 'antd';
import { BulbFilled, BulbOutlined } from '@ant-design/icons';
import { useLocation } from 'react-router-dom';
import { useThemeStore, useProjectStore } from '@/stores';
import { agentApi } from '@/api';
import type { AgentHealth } from '@/types/agent';

interface PageMeta {
  group: string;
  title: string;
  sub: string;
}

const PAGE_META: Record<string, PageMeta> = {
  '/chat': { group: '工作台', title: '智能对话', sub: 'ReAct / Hermes 双引擎问答' },
  '/review': { group: '工作台', title: '原理图审查', sub: '规则驱动的设计检查' },
  '/hitl': { group: '工作台', title: 'HITL 审批', sub: '人工复核沉淀规则与参数' },
  '/knowledge': { group: '数据', title: '知识库', sub: 'Datasheet 检索与分层知识管理' },
  '/etl': { group: '数据', title: 'ETL 导入', sub: 'PSTX 网表 → 器件-网络图谱' },
  '/graph': { group: '数据', title: '图谱可视化', sub: '器件关系 / 电源链路 / 故障溯源' },
  '/system': { group: '系统', title: '系统状态', sub: '服务健康、数据规模与 Agent 指标' },
};

const Header: React.FC = () => {
  const { theme, toggleTheme } = useThemeStore();
  const currentProject = useProjectStore((state) => state.currentProject);
  const location = useLocation();
  const meta = PAGE_META[location.pathname] ?? { group: '工作台', title: 'Hardware AI', sub: '' };
  const [health, setHealth] = useState<AgentHealth | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => {
      agentApi
        .health()
        .then((result) => {
          if (alive) setHealth(result);
        })
        .catch(() => {
          // 探测失败只影响状态点，绝不抛错打断页面
          if (alive) setHealth(null);
        })
        .finally(() => {
          if (alive) setChecked(true);
        });
    };
    load();
    const timer = window.setInterval(load, 60000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const engineState: 'ok' | 'warn' | 'off' = !health
    ? 'off'
    : health.enabled && health.upstream
      ? 'ok'
      : health.enabled
        ? 'warn'
        : 'off';
  const engineLabel = !checked
    ? '引擎检测中'
    : !health
      ? '引擎离线'
      : !health.enabled
        ? 'Hermes 未启用'
        : health.upstream
          ? 'Hermes 就绪'
          : '网关异常';
  const engineTip = health
    ? `经典引擎：可用 / Hermes：${health.enabled ? (health.upstream ? '网关正常' : '网关不可用') : '未开启'}${health.detail ? `（${health.detail}）` : ''}`
    : '无法读取 /api/v1/agent/health，仅影响 Hermes 引擎可用性提示';

  return (
    <header className="hx-header">
      <div className="hx-header-left">
        <div className="hx-crumb">
          <span className="hx-crumb-group">{meta.group}</span>
          <span className="hx-crumb-sep">/</span>
          <span>{meta.title}</span>
        </div>
        {meta.sub && <div className="hx-header-sub">{meta.sub}</div>}
      </div>

      <div className="hx-header-right">
        <Tooltip title={engineTip}>
          <span className="hx-engine">
            <i className="hx-dot" data-state={engineState} />
            {engineLabel}
          </span>
        </Tooltip>

        <Tooltip title={theme === 'dark' ? '切换到浅色' : '切换到深色'}>
          <Button
            className="hx-icon-btn"
            type="text"
            aria-label="切换主题"
            icon={theme === 'dark' ? <BulbFilled /> : <BulbOutlined />}
            onClick={toggleTheme}
          />
        </Tooltip>

        <Tooltip title="当前项目">
          <Tag className="hx-project-tag">{currentProject}</Tag>
        </Tooltip>
      </div>
    </header>
  );
};

export default Header;
