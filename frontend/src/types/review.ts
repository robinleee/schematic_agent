// Review types
export type Severity = 'ERROR' | 'WARNING' | 'INFO';

export interface Violation {
  rule_id: string;
  rule_name: string;
  refdes: string;
  net_name?: string;
  description: string;
  severity: Severity;
  expected?: string;
  actual?: string;
  suggested_fix?: string;
}

export interface RuleInfo {
  id: string;
  name: string;
  template_id: string;
  severity: Severity;
  enabled: boolean;
  description?: string;
}

export interface ReviewRequest {
  rule_ids?: string[];
  enabled_only: boolean;
}

export interface ReviewReport {
  total: number;
  errors: number;
  warnings: number;
  infos: number;
  by_rule: Record<string, number>;
  generated_at: string;
}

export interface ReviewResult {
  violations: Violation[];
  report_markdown: string;
  summary: ReviewReport;
}

export interface ReviewResponse {
  success: boolean;
  data: ReviewResult;
  message?: string;
  timestamp: string;
}

export interface RulesListResponse {
  success: boolean;
  data: RuleInfo[];
  message?: string;
  timestamp: string;
}
