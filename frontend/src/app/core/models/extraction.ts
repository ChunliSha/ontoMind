export type TaskType =
  | 'schema_induction'
  | 'instance_unstructured'
  | 'instance_structured'
  | 'business_logic'
  | 'business_logic_topology';

export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed';

export interface ExtractionTaskRead {
  id: string;
  task_type: TaskType;
  status: TaskStatus;
  progress: number;
  output_summary?: Record<string, unknown> | null;
  error_message?: string | null;
  schema_id?: string | null;
  created_at?: string;
}

export interface UnstructuredExtractionRequest {
  schema_id: string;
  file_ids: string[];
  ai_config?: Record<string, unknown> | null;
  model_id?: string | null;
  replace_existing?: boolean;
}

export interface StructuredExtractionRequest {
  schema_id: string;
  mapping_ids: string[];
  replace_existing?: boolean;
}

export interface BusinessLogicExtractionRequest {
  ontology_model_id?: string | null;
  schema_id?: string | null;
  file_ids: string[];
  ai_config?: Record<string, unknown> | null;
  model_id?: string | null;
  schema_version?: number | null;
  type_mapping?: Record<string, string[]> | null;
  name?: string | null;
}

export interface InstanceRead {
  id: string;
  schema_id: string;
  class_id: string | null;
  class_label?: string | null;
  label: string;
  local_name?: string | null;
  source_type: 'ai_unstructured' | 'structured_mapping' | 'manual';
  confidence?: number | null;
  schema_version?: number | null;
  created_at: string;
}

export interface InstanceDataValueWrite {
  property_id: string;
  value: string;
}

export interface InstanceRelationWrite {
  property_id: string;
  object_instance_id: string;
}

export interface InstanceUpdate {
  class_id: string | null;
  data_values: InstanceDataValueWrite[];
  relations: InstanceRelationWrite[];
}

export interface InstanceDetail extends InstanceRead {
  data_values: { property_id: string; property_label: string; value: string }[];
  relations: {
    property_id: string;
    property_label: string;
    object_instance_id: string;
    object_instance_label?: string | null;
    object_label?: string | null;
    object_class_label?: string | null;
    direction?: 'out' | 'in';
  }[];
}

export interface InstanceStat {
  class_id: string;
  class_label: string;
  count: number;
}

export interface InstanceStatsResponse {
  schema_id: string;
  schema_version?: number | null;
  total: number;
  by_class: InstanceStat[];
}

export interface InstanceInventory {
  schema_id: string;
  schema_name: string;
  schema_version: number;
  filter_version?: number | null;
  versions: number[];
  total: number;
  by_class: InstanceStat[];
  recent_tasks: ExtractionTaskRead[];
}

export interface ClearInstancesResult {
  deleted: number;
  schema_id: string;
  schema_version?: number | null;
}

export interface BusinessLogicRuleRead {
  id: string;
  schema_id: string;
  rule_type: 'causality' | 'constraint';
  description: string;
  condition: Record<string, unknown>;
  consequence?: Record<string, unknown> | null;
  action_required?: string | null;
  severity?: string | null;
  created_at: string;
}
