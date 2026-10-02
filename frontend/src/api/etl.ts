// ETL API
import apiClient from './client';
import type {
  ETLPreviewResponse,
  ETLResponse,
  ProjectListResponse,
  ProjectActionResponse,
  ETLProgress,
} from '@/types/etl';

export const etlApi = {
  getProjects: async (): Promise<ProjectListResponse> => {
    const response = await apiClient.get<ProjectListResponse>('/etl/projects');
    return response.data;
  },

  createProject: async (projectName: string): Promise<ProjectActionResponse> => {
    const response = await apiClient.post<ProjectActionResponse>('/etl/projects', {
      project_name: projectName,
    });
    return response.data;
  },

  deleteProject: async (projectName: string): Promise<ProjectActionResponse> => {
    const response = await apiClient.delete<ProjectActionResponse>(`/etl/projects/${encodeURIComponent(projectName)}`);
    return response.data;
  },

  preview: async (
    pstxnet: File,
    pstxprt: File,
    pstchip: File,
    bom?: File
  ): Promise<ETLPreviewResponse> => {
    const formData = new FormData();
    formData.append('pstxnet', pstxnet);
    formData.append('pstxprt', pstxprt);
    formData.append('pstchip', pstchip);
    if (bom) formData.append('bom', bom);

    const response = await apiClient.post<ETLPreviewResponse>('/etl/preview', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  run: async (
    pstxnet: File,
    pstxprt: File,
    pstchip: File,
    projectName: string = 'default',
    bom?: File
  ): Promise<ETLResponse> => {
    const formData = new FormData();
    formData.append('pstxnet', pstxnet);
    formData.append('pstxprt', pstxprt);
    formData.append('pstchip', pstchip);
    formData.append('project_name', projectName);
    if (bom) formData.append('bom', bom);

    const response = await apiClient.post<ETLResponse>('/etl/run', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  getProgress: async (jobId: string): Promise<ETLProgress> => {
    const response = await apiClient.get<ETLProgress>(`/etl/progress/${jobId}`);
    return response.data;
  },
};

export default etlApi;
