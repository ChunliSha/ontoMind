export interface TopologyEndpoint {
  cell: string;
  port?: string | null;
}

export interface TopologyNode {
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  color?: string | null;
  extension_id?: string | null;
  properties: Record<string, unknown>;
}

export interface TopologyEdge {
  id: string;
  source: TopologyEndpoint;
  target: TopologyEndpoint;
  label?: string;
}

export interface TopologyGraph {
  workflow_id: string;
  name: string;
  description?: string;
  created_at?: string | null;
  last_updated?: string | null;
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

export interface NodeTypeRead {
  type_key: string;
  color: string;
  extension_id: string;
  role: string;
}

export interface TypeMappingCandidate {
  class_id: string;
  class_label: string;
  local_name?: string | null;
  instance_count: number;
  type_key: string;
  score: number;
  reasons: string[];
}

export interface TypeMappingItem {
  type_key: string;
  class_ids: string[];
  class_labels: string[];
  instance_count: number;
  candidates?: TypeMappingCandidate[];
}

export interface UnmappedClass {
  class_id: string;
  class_label: string;
  local_name?: string | null;
  instance_count: number;
}

export interface TypeMappingSuggestResponse {
  schema_id: string;
  schema_version?: number | null;
  instance_count: number;
  mapping: TypeMappingItem[];
  unmapped_classes: UnmappedClass[];
}

export interface CatalogInstance {
  id: string;
  label: string;
  local_name?: string | null;
  class_id: string;
  class_label: string;
}

export interface TypeCatalogItem {
  type_key: string;
  class_ids: string[];
  instances: CatalogInstance[];
}

export interface InstanceCatalogResponse {
  schema_id: string;
  schema_version?: number | null;
  mapping: TypeMappingItem[];
  by_type: TypeCatalogItem[];
  instances?: CatalogInstance[];
}

export interface TopologyWarning {
  level?: string;
  code?: string;
  message: string;
}

export interface TopologySummary {
  id: string;
  schema_id: string;
  schema_version?: number | null;
  ontology_model_id?: string | null;
  name: string;
  description?: string;
  node_count: number;
  edge_count: number;
  grounded_ratio?: number | null;
  layout_locked: boolean;
  status: string;
  extraction_task_id?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface TopologyRead extends TopologySummary {
  source_file_ids: string[];
  graph: TopologyGraph;
  validation?: Record<string, unknown> | null;
  warnings: TopologyWarning[];
  type_mapping: Record<string, string[]>;
}

export interface TopologyPatchRequest {
  name?: string | null;
  description?: string | null;
  layout_locked?: boolean | null;
  graph?: TopologyGraph | Record<string, unknown> | null;
  remount?: { node_id: string; instance_id?: string | null } | null;
  add_edge?: { source_id: string; target_id: string; label?: string } | null;
  delete_edge_ids?: string[] | null;
  update_node?: {
    id: string;
    label?: string | null;
    x?: number | null;
    y?: number | null;
    properties?: Record<string, unknown> | null;
  } | null;
}
