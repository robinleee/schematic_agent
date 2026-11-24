// Axios client configuration
import axios from 'axios';

// FastAPI errors can be a string or a list of validation issues.
export function apiErrorText(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail;
    const text = Array.isArray(detail)
      ? detail.map((issue: unknown) => {
          if (typeof issue !== 'object' || issue === null) return '请求: 参数无效';
          const item = issue as { loc?: unknown; msg?: unknown };
          const loc = Array.isArray(item.loc) ? item.loc.join('.') : '请求';
          return `${loc}: ${typeof item.msg === 'string' ? item.msg : '参数无效'}`;
        }).join('; ')
      : typeof detail === 'string' ? detail : undefined;
    const data: unknown = error.response?.data;
    const job = data && typeof data === 'object' ? data as {
      error?: unknown; message?: unknown; result?: { message?: unknown };
    } : null;
    const failure = job?.error || job?.result?.message || job?.message;
    const reason = text || (typeof failure === 'string' ? failure : undefined) || error.message;
    return `${error.response?.status ? `HTTP ${error.response.status}: ` : ''}${reason}`;
  }
  return error instanceof Error ? error.message : String(error);
}

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    // Add auth token if available
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized
      localStorage.removeItem('auth_token');
    }
    return Promise.reject(error);
  }
);

export default apiClient;
