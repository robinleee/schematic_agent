// Header component
import React from 'react';
import { Layout, Switch, Typography, Space } from 'antd';
import { BulbOutlined, BulbFilled } from '@ant-design/icons';
import { useThemeStore } from '@/stores';

const { Header: AntHeader } = Layout;
const { Title } = Typography;

const Header: React.FC = () => {
  const { theme, toggleTheme } = useThemeStore();

  return (
    <AntHeader
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: theme === 'dark' ? '#141414' : '#fff',
        padding: '0 24px',
        borderBottom: '1px solid #f0f0f0',
      }}
    >
      <Title level={4} style={{ margin: 0 }}>
        Hardware AI Expert
      </Title>
      <Space>
        <Switch
          checked={theme === 'dark'}
          onChange={toggleTheme}
          checkedChildren={<BulbFilled />}
          unCheckedChildren={<BulbOutlined />}
        />
      </Space>
    </AntHeader>
  );
};

export default Header;
