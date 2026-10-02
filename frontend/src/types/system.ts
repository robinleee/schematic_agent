// System types
export type ServiceStatusType = 'running' | 'stopped' | 'error' | 'degraded';

export interface ServiceInfo {
  name: string;
  status: ServiceStatusType;
  latency_ms?: number;
  version?: string;
  message?: string;
}

export interface DataStats {
  components: number | null;
  pins: number | null;
  nets: number | null;
  part_type_coverage: number | null;
  by_parttype: Record<string, number>;
  status: 'available' | 'unavailable';
}

export interface QueryRecord {
  query: string;
  task_type: string;
  tool_calls: number;
  duration_ms: number;
  timestamp: string;
}

export interface AgentStats {
  query_count: number;
  token_usage: number | null;
  recent_queries: QueryRecord[];
  status: string;
  message: string;
}

export interface SystemStatus {
  services: ServiceInfo[];
  data_stats: DataStats;
  agent_stats: AgentStats;
}

export interface SystemStatusResponse {
  success: boolean;
  data: SystemStatus;
  message?: string;
  timestamp: string;
}
