import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from 'react-query';
import { ConfigProvider, Spin } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { AppLayout } from '@/components/Layout';
import { buildTheme } from '@/theme/tokens';
import { useThemeStore } from '@/stores';

// Lazy load pages
const Chat = React.lazy(() => import('@/pages/Chat'));
const Review = React.lazy(() => import('@/pages/Review'));
const HITL = React.lazy(() => import('@/pages/HITL'));
const Knowledge = React.lazy(() => import('@/pages/Knowledge'));
const ETL = React.lazy(() => import('@/pages/ETL'));
const Graph = React.lazy(() => import('@/pages/Graph'));
const System = React.lazy(() => import('@/pages/System'));

// Create QueryClient
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Loading fallback
const LoadingFallback: React.FC = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
    <Spin size="large" />
  </div>
);

const App: React.FC = () => {
  const theme = useThemeStore((state) => state.theme);

  // 让 global.css 的 CSS 变量跟随 antd 的明暗算法
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN} theme={buildTheme(theme === 'dark')}>
        <BrowserRouter>
          <React.Suspense fallback={<LoadingFallback />}>
            <Routes>
              <Route path="/" element={<AppLayout />}>
                <Route index element={<Navigate to="/chat" replace />} />
                <Route path="chat" element={<Chat />} />
                <Route path="review" element={<Review />} />
                <Route path="hitl" element={<HITL />} />
                <Route path="knowledge" element={<Knowledge />} />
                <Route path="etl" element={<ETL />} />
                <Route path="graph" element={<Graph />} />
                <Route path="system" element={<System />} />
              </Route>
            </Routes>
          </React.Suspense>
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  );
};

export default App;
