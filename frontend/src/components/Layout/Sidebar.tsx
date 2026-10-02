// Sidebar navigation
import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Menu } from 'antd';
import {
  MessageOutlined,
  AuditOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  UploadOutlined,
  ApartmentOutlined,
  DesktopOutlined,
} from '@ant-design/icons';

const menuItems = [
  {
    key: '/chat',
    icon: <MessageOutlined />,
    label: '智能对话',
  },
  {
    key: '/review',
    icon: <AuditOutlined />,
    label: '原理图审查',
  },
  {
    key: '/hitl',
    icon: <CheckCircleOutlined />,
    label: 'HITL 审批',
  },
  {
    key: '/knowledge',
    icon: <DatabaseOutlined />,
    label: '知识库管理',
  },
  {
    key: '/etl',
    icon: <UploadOutlined />,
    label: 'ETL 导入',
  },
  {
    key: '/graph',
    icon: <ApartmentOutlined />,
    label: '图谱可视化',
  },
  {
    key: '/system',
    icon: <DesktopOutlined />,
    label: '系统状态',
  },
];

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <Menu
      mode="inline"
      selectedKeys={[location.pathname]}
      items={menuItems}
      onClick={({ key }) => navigate(key)}
      style={{ height: '100%', borderRight: 0 }}
    />
  );
};

export default Sidebar;
