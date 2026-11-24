// Hermes agent run types

export type ApprovalChoice = 'once' | 'session' | 'always' | 'deny';

export type ApprovalStatus = 'pending' | 'approved' | 'denied' | 'expired' | 'error';

export interface ApprovalState {
  runId: string;
  requestId: string;
  tool?: string;
  command?: string;
  description?: string;
  choices: ApprovalChoice[];
  status: ApprovalStatus;
  choice?: ApprovalChoice;
  error?: string;
  /** epoch ms，前端倒计时到点自动拒绝 */
  deadline?: number;
}

export interface AgentRunEvent {
  event: string;
  run_id?: string;
  seq?: number;
  timestamp?: number;
  // message.delta
  delta?: string;
  // tool.started / tool.completed
  tool?: string;
  preview?: string | null;
  duration?: number;
  error?: boolean;
  // reasoning.available
  text?: string;
  // approval.request
  request_id?: string;
  choices?: string[];
  command?: string;
  description?: string;
  // approval.responded
  resolved?: number;
  // run.completed
  output?: string;
  status?: string;
}

export interface AgentRunCreateResponse {
  run_id: string;
  status?: string;
  session_id?: string;
  replayed?: boolean;
}

export interface AgentRunState {
  run_id: string;
  status: string;
  output?: string;
  last_event?: string;
  completed?: boolean;
}

export interface AgentHealth {
  enabled: boolean;
  upstream: boolean;
  detail?: string;
  bound_project?: string | null;
  base_url?: string;
}

export const APPROVAL_LABELS: Record<ApprovalChoice, string> = {
  once: '仅本次允许',
  session: '本会话内允许',
  always: '总是允许',
  deny: '拒绝',
};
