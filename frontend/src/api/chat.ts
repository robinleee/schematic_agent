// Chat API
import apiClient from './client';
import type { ChatRequest, ChatResponse } from '@/types/chat';

export const chatApi = {
  sendMessage: async (request: ChatRequest): Promise<ChatResponse> => {
    const response = await apiClient.post<ChatResponse>('/chat', request, { timeout: 310000 });
    return response.data;
  },
};

export default chatApi;
