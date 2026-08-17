export type SchemaStatus = 'draft' | 'published';
export type PropertyKind = 'data' | 'object';
export type SourceKind = 'manual' | 'ai' | 'ai_induced' | 'imported_ttl';

export interface SchemaRead {
  id: string;
  name: string;
  base_iri?: string;
  status: SchemaStatus;
  version: number;
  class_count: number;
  property_count: number;
  change_log?: string | null;
  published_at?: string | null;
  source?: string;
  updated_at: string;
  created_at?: string;
}

export interface SchemaCreate {
  name: string;
  base_iri?: string;
}

export interface SchemaPublishRequest {
  change_log?: string | null;
}

export interface ClassRead {
  id: string;
  schema_id: string;
  label: string;
  local_name?: string | null;
  parent_class_id?: string | null;
  description?: string | null;
  source: 'manual' | 'ai';
  property_count?: number;
  cnt?: number;
}

export interface ClassCreate {
  label: string;
  local_name?: string | null;
  parent_class_id?: string | null;
  description?: string | null;
}

export interface PropertyRead {
  id: string;
  label: string;
  kind: PropertyKind;
  datatype?: string | null;
  range_class_id?: string | null;
  range_class_label?: string | null;
  required: boolean;
  multi: boolean;
  source: 'manual' | 'ai';
  confidence?: number | null;
  domain_class_id?: string;
}

export interface PropertyCreate {
  label: string;
  kind: PropertyKind;
  datatype?: string | null;
  range_class_id?: string | null;
  required?: boolean;
  multi?: boolean;
}
