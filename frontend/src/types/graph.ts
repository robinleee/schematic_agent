// Graph types
export type VizMode = 'component' | 'power_chain' | 'fault_trace' | 'common_cause' | 'power_tree';
export type Direction = 'upstream' | 'downstream' | 'both';

export interface GraphRequest {
  mode: VizMode;
  refdes?: string;
  depth: number;
  direction: Direction;
  voltage?: string;
}

export interface GraphResult {
  dot_content: string;
  node_count: number;
  edge_count: number;
}

export interface GraphResponse {
  success: boolean;
  data: GraphResult;
  message?: string;
  timestamp: string;
}
