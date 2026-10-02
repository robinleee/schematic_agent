// Knowledge types
export type KnowledgeCategory = 'datasheet' | 'design_guide' | 'application_note' | 'general';

export interface SearchRequest {
  project_id?: string;
  mpn?: string;
  query: string;
  max_results: number;
}

export interface SearchResult {
  status: 'success' | 'not_found' | 'error' | string;
  tier: string;
  content: string;
  source: string;
  confidence: number;
  mpn?: string;
  cached: boolean;
}

export interface SearchResponse {
  success: boolean;
  data: SearchResult;
  message?: string;
  timestamp: string;
}

export interface KnowledgeStats {
  tier1_chunks: number;
  tier2_enabled: boolean;
  tier3_enabled: boolean;
  source_distribution: Record<string, number>;
}

export interface KnowledgeStatsResponse {
  success: boolean;
  data: KnowledgeStats;
  message?: string;
  timestamp: string;
}

export interface UploadResponse {
  success: boolean;
  data: {
    chunk_count: number;
    mpn: string;
    file_name?: string;
    indexed_at?: string;
  };
  message?: string;
  timestamp: string;
}
