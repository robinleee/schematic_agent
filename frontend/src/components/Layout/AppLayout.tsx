// Main layout component：Sider(232) + Header(56) + Content(可滚动)
import React from 'react';
import { Layout } from 'antd';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import { useThemeStore } from '@/stores';

const { Sider, Content } = Layout;

const AppLayout: React.FC = () => {
  const theme = useThemeStore((state) => state.theme);
  const dark = theme === 'dark';

  return (
    <Layout className="hx-shell" hasSider>
      <Sider
        className="hx-sider"
        width={232}
        theme={dark ? 'dark' : 'light'}
        breakpoint="lg"
        collapsedWidth={0}
      >
        <Sidebar />
      </Sider>
      <Layout>
        <Header />
        <Content className="hx-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
};

export default AppLayout;
