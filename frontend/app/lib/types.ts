export type ApiResult<T> = {
  data: T | null;
  error: string | null;
  status: number;
};

export type Season = {
  id: number;
  event_type: string;
  server: string;
  boss_name: string;
  armor_type: string | null;
  terrain: string;
  season_label: string;
  started_at: string | null;
  ended_at: string | null;
};

export type RankingSnapshot = {
  id: number;
  season_id: number;
  captured_at: string;
  source_type: string;
  status: string;
  total_rows_collected: number | null;
  note: string | null;
};

export type RankingEntry = {
  id: number;
  ranking_snapshot_id: number;
  rank: number;
  score: number;
  player_name: string | null;
  ocr_confidence: number | null;
  raw_text: string | null;
  image_path: string | null;
  is_valid: boolean;
  validation_issue: string | null;
};

export type ValidationIssueFilter = string;

export type RankingSnapshotValidationIssueCount = {
  code: string;
  count: number;
};

export type CollectorIgnoredReasonCount = {
  reason: string;
  count: number;
};

export type CollectorReasonCount = {
  reason: string;
  count: number;
};

export type CollectorPageSummary = {
  page_index: number;
  image_path: string;
  entry_count: number;
  ignored_line_count: number;
  ignored_line_reasons: CollectorIgnoredReasonCount[];
  first_rank: number | null;
  last_rank: number | null;
  overlap_with_previous_count: number;
  overlap_with_previous_ratio: number;
  new_rank_count: number;
  new_rank_ratio: number;
};

export type CollectorStopHint = {
  reason: string;
  page_index: number | null;
  entry_count: number | null;
  ignored_line_count: number | null;
  overlap_with_previous_count: number | null;
  overlap_with_previous_ratio: number | null;
  new_rank_count: number | null;
  new_rank_ratio: number | null;
};

export type CollectorStopRecommendation = {
  should_stop: boolean;
  level: string | null;
  primary_reason: string | null;
  reasons: string[];
};

export type CollectorDiagnostics = {
  raw_summary: string;
  captured_page_count: number | null;
  requested_page_count: number | null;
  capture_stop_reason: string | null;
  ignored_line_count: number;
  ignored_reasons: CollectorIgnoredReasonCount[];
  ocr_stop_reason: string | null;
  ocr_stop_level: string | null;
  page_summaries: CollectorPageSummary[];
  ocr_stop_hints: CollectorStopHint[];
  ocr_stop_recommendation: CollectorStopRecommendation | null;
};

export type ValidationTopIssue = {
  code: string;
  count: number;
};

export type RankingSnapshotValidationReport = {
  snapshot_id: number;
  status: string;
  total_entry_count: number;
  valid_entry_count: number;
  invalid_entry_count: number;
  excluded_from_statistics_count: number;
  invalid_ratio: number;
  duplicate_rank_count: number;
  has_rank_order_violation: boolean;
  top_validation_issue: ValidationTopIssue | null;
  validation_issues: RankingSnapshotValidationIssueCount[];
  collector_diagnostics: CollectorDiagnostics | null;
};

export type SeasonValidationOverview = {
  season_id: number;
  snapshot_count: number;
  completed_snapshot_count: number;
  collecting_snapshot_count: number;
  failed_snapshot_count: number;
  total_entry_count: number;
  valid_entry_count: number;
  invalid_entry_count: number;
  excluded_from_statistics_count: number;
  invalid_ratio: number;
  top_validation_issue: ValidationTopIssue | null;
  validation_issues: RankingSnapshotValidationIssueCount[];
  snapshots_with_collector_diagnostics_count: number;
  snapshots_with_capture_stop_count: number;
  snapshots_with_hard_ocr_stop_count: number;
  total_ignored_line_count: number;
  capture_stop_reasons: CollectorReasonCount[];
  ocr_stop_reasons: CollectorReasonCount[];
  ignored_reasons: CollectorIgnoredReasonCount[];
};

export type SeasonValidationSeriesPoint = {
  snapshot_id: number;
  captured_at: string;
  status: string;
  total_entry_count: number;
  valid_entry_count: number;
  invalid_entry_count: number;
  invalid_ratio: number;
  top_validation_issue: ValidationTopIssue | null;
  collector_diagnostics: CollectorDiagnostics | null;
};

export type SeasonValidationSeries = {
  season_id: number;
  points: SeasonValidationSeriesPoint[];
};

export type RankingSnapshotSummary = {
  snapshot_id: number;
  season_id: number;
  status: string;
  captured_at: string;
  total_rows_collected: number | null;
  valid_entry_count: number;
  invalid_entry_count: number;
  highest_score: number | null;
  lowest_score: number | null;
  validation_issues: RankingSnapshotValidationIssueCount[];
};

export type RankingSnapshotCutoff = {
  rank: number;
  score: number | null;
};

export type RankingSnapshotCutoffs = {
  snapshot_id: number;
  status: string;
  cutoffs: RankingSnapshotCutoff[];
};

export type RankingSnapshotDistribution = {
  snapshot_id: number;
  status: string;
  count: number;
  min_score: number | null;
  max_score: number | null;
  avg_score: number | null;
  median_score: number | null;
};

export type SeasonCutoffSeriesPoint = {
  snapshot_id: number;
  captured_at: string;
  score: number | null;
};

export type SeasonCutoffSeries = {
  season_id: number;
  rank: number;
  points: SeasonCutoffSeriesPoint[];
};
