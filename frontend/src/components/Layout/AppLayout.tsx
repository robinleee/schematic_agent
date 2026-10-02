// Main layout component
import React from 'react';
import { Layout, ConfigProvider, theme as antdTheme } from 'antd';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import { useThemeStore } from '@/stores';

const { Sider, Content } = Layout;

const AppLayout: React.FC = () => {
  const { theme } = useThemeStore();

  return (
    <ConfigProvider
      theme={{
        algorithm: theme === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: '#1890ff',
          borderRadius: 6,
        },
      }}
    >
      <Layout style={{ minHeight: '100vh' }}>
        <Sider
          width={200}
          style={{
            background: theme === 'dark' ? '#1f1f1f' : '#fff',
          }}
          breakpoint="md"
          collapsedWidth={0}
        >
          <Sidebar />
        </Sider>
        <Layout>
          <Header />
          <Content
            style={{
              margin: '24px',
              padding: '24px',
              background: theme === 'dark' ? '#141414' : '#fff',
              borderRadius: '8px',
              minHeight: 'calc(100vh - 112px)',
              overflow: 'auto',
            }}
          >
            <Outlet />
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
};

export default AppLayout;
