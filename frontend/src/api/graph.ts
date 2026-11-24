// Graph API
import apiClient from './client';
import type { GraphRequest, GraphResponse } from '@/types/graph';

export const graphApi = {
  visualize: async (request: GraphRequest): Promise<GraphResponse> => {
    const response = await apiClient.post<GraphResponse>('/graph/visualize', request);
    return response.data;
  },
};

export default graphApi;
