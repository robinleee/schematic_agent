// ETL types
export type ETLStep = 'pending' | 'parsing' | 'validating' | 'loading' | 'completed' | 'failed';

export interface ETLPreviewResult {
  success: boolean;
  components_count: number | null;
  topology_count: number | null;
  unique_nets: number | null;
  parttype_coverage: number | null;
  parttype_distribution: Record<string, number>;
  power_nets_count: number | null;
  ground_nets_count: number | null;
  top_nets: string[];
  bom_enriched_components: number | null;
  bom_issues: Record<string, unknown>[];
}

export interface ETLPreviewResponse {
  success: boolean;
  data: ETLPreviewResult;
  message?: string;
  timestamp: string;
}

export interface ETLProgress {
  job_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timeout';
  step: ETLStep;
  progress: number;
  message: string;
  error: string | null;
  result: ETLResult | null;
  created_at: string;
  updated_at: string;
}

export interface QualityReport {
  components: number | null;
  pins: number | null;
  nets: number | null;
  part_type_coverage: number | null;
  passed: boolean;
  details?: Record<string, unknown>;
}

export interface ETLResult {
  success: boolean;
  components_count: number | null;
  topology_count: number | null;
  parttype_coverage: number | null;
  quality_passed: boolean;
  message: string;
  quality_report?: QualityReport;
  bom_issues: Record<string, unknown>[];
}

export interface ETLResponse {
  success: boolean;
  job_id: string;
  status: string;
  data: ETLResult | null;
  message?: string;
  timestamp: string;
}

export interface ProjectListResponse {
  success: boolean;
  data: string[];
  message?: string;
  timestamp: string;
}

export interface ProjectActionResponse {
  success: boolean;
  data: Record<string, string>;
  message?: string;
  timestamp: string;
}

export interface ProjectDeleteResult {
  project_id: string;
  deleted_nodes: string;
  deleted_vectors: Record<string, number>;
}

export interface ProjectDeleteResponse {
  success: boolean;
  data: ProjectDeleteResult;
  message?: string;
  timestamp: string;
}
