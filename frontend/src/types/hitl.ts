// HITL types
export type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'persisted';

export interface PendingReview {
  review_id: string;
  rule_id: string;
  rule_name: string;
  refdes: string;
  net_name?: string;
  description: string;
  severity: string;
  expected?: string;
  actual?: string;
  suggested_fix?: string;
  status: ReviewStatus;
  reviewer?: string;
  review_comment?: string;
  reviewed_at?: string;
  created_at: string;
  source: string;
}

export interface ReviewActionRequest {
  review_ids: string[];
  action: 'approve' | 'reject';
  comment?: string;
  reviewer?: string;
}

export interface ReviewActionResponse {
  success: boolean;
  data: {
    results: { review_id: string; action: 'approve' | 'reject'; success: boolean; error?: string }[];
    succeeded: number;
    failed: number;
  };
  message?: string;
  timestamp: string;
}

export interface ExportResponse {
  success: boolean;
  data: {
    saved: number;
    rules: string[];
    location: string | null;
  };
  message?: string;
  timestamp: string;
}

export interface DatasheetPendingReview {
  review_id: string;
  mpn: string;
  param_type: string;
  param_name: string;
  value: number;
  unit: string;
  min_value?: number;
  max_value?: number;
  condition: string;
  source_text: string;
  confidence: number;
  extraction_method: string;
  status: string;
  reviewer?: string;
  review_comment?: string;
  reviewed_at?: string;
  created_at: string;
  source_file: string;
}

export interface DatasheetPendingListResponse {
  success: boolean;
  data: DatasheetPendingReview[];
  total: number;
  message?: string;
  timestamp: string;
}

export interface DatasheetPersistResponse {
  success: boolean;
  data: { saved: number; message?: string; error?: string };
  message?: string;
  timestamp: string;
}

