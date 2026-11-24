// Sidebar navigation：品牌区 + 分组导航
import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Menu } from 'antd';
import type { MenuProps } from 'antd';
import {
  MessageOutlined,
  AuditOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  UploadOutlined,
  ApartmentOutlined,
  DesktopOutlined,
} from '@ant-design/icons';
import { useThemeStore } from '@/stores';

const menuItems: MenuProps['items'] = [
  {
    key: 'grp-workbench',
    type: 'group',
    label: '工作台',
    children: [
      { key: '/chat', icon: <MessageOutlined />, label: '智能对话' },
      { key: '/review', icon: <AuditOutlined />, label: '原理图审查' },
      { key: '/hitl', icon: <CheckCircleOutlined />, label: 'HITL 审批' },
    ],
  },
  {
    key: 'grp-data',
    type: 'group',
    label: '数据',
    children: [
      { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库' },
      { key: '/etl', icon: <UploadOutlined />, label: 'ETL 导入' },
      { key: '/graph', icon: <ApartmentOutlined />, label: '图谱可视化' },
    ],
  },
  {
    key: 'grp-system',
    type: 'group',
    label: '系统',
    children: [
      { key: '/system', icon: <DesktopOutlined />, label: '系统状态' },
    ],
  },
];

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useThemeStore((state) => state.theme);
  const dark = theme === 'dark';

  return (
    <>
      <div className="hx-brand">
        <div className="hx-brand-mark">H</div>
        <div className="hx-brand-text">
          <span className="hx-brand-name">Hardware AI</span>
          <span className="hx-brand-sub">Expert Console</span>
        </div>
      </div>
      <div className="hx-nav">
        <Menu
          mode="inline"
          theme={dark ? 'dark' : 'light'}
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none', background: 'transparent' }}
        />
      </div>
    </>
  );
};

export default Sidebar;
