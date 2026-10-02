// Chat store
import { create } from 'zustand';
import type { Message, ReasoningStep } from '@/types/chat';

interface ChatState {
  messages: Message[];
  isLoading: boolean;
  currentTaskType: 'review' | 'diagnosis' | 'query' | null;
  addMessage: (message: Message) => void;
  updateLastAssistantMessage: (content: string, trace?: ReasoningStep[]) => void;
  setLoading: (loading: boolean) => void;
  setTaskType: (type: 'review' | 'diagnosis' | 'query' | null) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  currentTaskType: null,
  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),
  updateLastAssistantMessage: (content, trace) =>
    set((state) => {
      const messages = [...state.messages];
      const lastIndex = messages.length - 1;
      if (lastIndex >= 0 && messages[lastIndex].role === 'assistant') {
        messages[lastIndex] = {
          ...messages[lastIndex],
          content,
          reasoningTrace: trace,
        };
      }
      return { messages };
    }),
  setLoading: (loading) => set({ isLoading: loading }),
  setTaskType: (type) => set({ currentTaskType: type }),
  clearMessages: () => set({ messages: [] }),
}));

export default useChatStore;
