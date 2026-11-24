// System API
import apiClient from './client';
import type { SystemStatusResponse } from '@/types/system';

export const systemApi = {
  getStatus: async (): Promise<SystemStatusResponse> => {
    const response = await apiClient.get<SystemStatusResponse>('/system/status');
    return response.data;
  },

  healthCheck: async (): Promise<{ success: boolean; message: string; timestamp: string }> => {
    const response = await apiClient.get('/health');
    return response.data;
  },
};

export default systemApi;
