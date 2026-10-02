// HITL API
import apiClient from './client';
import type { ReviewActionRequest, ReviewActionResponse, ExportResponse } from '@/types/hitl';
import type { PendingReview } from '@/types/hitl';

export const hitlApi = {
  getPending: async (
    status?: string,
    page: number = 1,
    pageSize: number = 50
  ): Promise<{
    success: boolean;
    data: PendingReview[];
    total: number;
    page: number;
    page_size: number;
    timestamp: string;
  }> => {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    params.append('page', String(page));
    params.append('page_size', String(pageSize));
    
    const response = await apiClient.get(`/hitl/pending?${params.toString()}`);
    return response.data;
  },

  reviewAction: async (request: ReviewActionRequest): Promise<ReviewActionResponse> => {
    const response = await apiClient.post<ReviewActionResponse>('/hitl/action', request);
    return response.data;
  },

  export: async (): Promise<ExportResponse> => {
    const response = await apiClient.post<ExportResponse>('/hitl/export', {});
    return response.data;
  },
};

export default hitlApi;
