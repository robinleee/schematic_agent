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
