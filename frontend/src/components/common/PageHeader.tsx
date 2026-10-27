// 页面级标题：标题 + 描述 + 右侧操作（统一各页头部结构）
import React from 'react';

interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  extra?: React.ReactNode;
}

const PageHeader: React.FC<PageHeaderProps> = ({ title, description, extra }) => (
  <div className="page-header">
    <div className="page-header-text">
      <h1 className="page-title">{title}</h1>
      {description && <p className="page-desc">{description}</p>}
    </div>
    {extra && <div className="page-actions">{extra}</div>}
  </div>
);

export default PageHeader;
