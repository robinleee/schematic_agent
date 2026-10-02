// WebSocket hook for streaming chat
import { useState, useCallback, useRef, useEffect } from 'react';
import type { ChatResult, ReasoningStep } from '@/types/chat';

interface UseWebSocketOptions {
  onStep?: (step: ReasoningStep) => void;
  onResult?: (result: ChatResult) => void;
  onError?: (error: string) => void;
}

export function useChatWebSocket(options: UseWebSocketOptions = {}) {
  const [isConnected, setIsConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const callbacks = useRef(options);
  callbacks.current = options;

  const connect = useCallback(() => {
    if (socketRef.current && socketRef.current.readyState <= WebSocket.OPEN) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const apiUrl = import.meta.env.VITE_API_URL
      ? new URL(import.meta.env.VITE_API_URL, window.location.href) : null;
    const wsProtocol = apiUrl ? (apiUrl.protocol === 'https:' ? 'wss:' : 'ws:') : protocol;
    const wsUrl = import.meta.env.VITE_WS_URL || `${wsProtocol}//${apiUrl?.host || host}/ws/chat`;
    const token = localStorage.getItem('auth_token');
    // RFC 6455 subprotocol tokens cannot contain arbitrary UTF-8 or spaces.
    // Offer the secret as base64url, but negotiate only the public chat.v1.
    const encodedToken = token
      ? btoa(String.fromCharCode(...new TextEncoder().encode(token)))
          .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
      : null;
    const socket = new WebSocket(wsUrl, encodedToken
      ? ['chat.v1', `chat.bearer.${encodedToken}`] : ['chat.v1']);

    socket.onopen = () => {
      setIsConnected(true);
    };

    socket.onclose = () => {
      setIsConnected(false);
      socketRef.current = null;
      callbacks.current.onError?.('WebSocket 连接已断开');
    };

    socket.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'step') {
          callbacks.current.onStep?.(data.payload.step);
        } else if (data.type === 'result') {
          callbacks.current.onResult?.(data.payload.result);
        } else if (data.type === 'error') {
          callbacks.current.onError?.(data.payload.error);
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    socketRef.current = socket;
  }, []);

  const disconnect = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.onclose = null;
      socketRef.current.close();
      socketRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const send = useCallback(
    (message: string, taskType?: string): boolean => {
      if (socketRef.current && isConnected) {
        socketRef.current.send(
          JSON.stringify({
            type: 'chat',
            payload: { message, task_type: taskType || 'auto' },
          })
        );
        return true;
      }
      return false;
    },
    [isConnected]
  );

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    connect,
    disconnect,
    send,
    isConnected,
  };
}

export default useChatWebSocket;
