// Review API
import apiClient from './client';
import type { ReviewRequest, ReviewResponse, RulesListResponse } from '@/types/review';

export const reviewApi = {
  getRules: async (): Promise<RulesListResponse> => {
    const response = await apiClient.get<RulesListResponse>('/review/rules');
    return response.data;
  },

  runReview: async (request: ReviewRequest): Promise<ReviewResponse> => {
    const response = await apiClient.post<ReviewResponse>('/review/run', request);
    return response.data;
  },
};

export default reviewApi;
