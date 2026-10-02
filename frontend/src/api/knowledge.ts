// Knowledge API
import apiClient from './client';
import type { SearchRequest, SearchResponse, KnowledgeStatsResponse, UploadResponse } from '@/types/knowledge';

export const knowledgeApi = {
  upload: async (
    file: File,
    mpn: string,
    category: string = 'general',
    projectId: string,
    source?: string
  ): Promise<UploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('mpn', mpn);
    formData.append('category', category);
    formData.append('project_id', projectId);
    if (source) formData.append('source', source);

    const response = await apiClient.post<UploadResponse>('/knowledge/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  search: async (request: SearchRequest): Promise<SearchResponse> => {
    const response = await apiClient.post<SearchResponse>('/knowledge/search', request);
    return response.data;
  },

  getStats: async (): Promise<KnowledgeStatsResponse> => {
    const response = await apiClient.get<KnowledgeStatsResponse>('/knowledge/stats');
    return response.data;
  },
};

export default knowledgeApi;
