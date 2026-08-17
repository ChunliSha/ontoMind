export interface DashboardSummary {
  data_source_count: number;
  structured_count: number;
  unstructured_count: number;
  schema_count: number;
  class_count: number;
  instance_count: number;
  graph_version_count: number;
  data_source_trend?: number;
  schema_trend?: number;
  instance_trend?: number;
}

export interface ActivityItem {
  id: string;
  module: string;
  text: string;
  color?: string;
  created_at: string;
}
