export interface SourceField {
  column_name: string;
  data_type: string;
  is_primary_key: boolean;
}

export interface TargetProperty {
  id: string | null;
  label: string;
  kind: 'instance_uri' | 'data' | 'object';
  datatype?: string | null;
}

export interface MappingBinding {
  target_kind: 'instance_uri' | 'property';
  target_property_id?: string | null;
  source_column: string;
}

export interface MappingRead {
  id: string;
  schema_id: string;
  class_id: string;
  table_id: string;
  bindings: MappingBinding[];
  updated_at?: string;
}

export interface MappingCreate {
  schema_id: string;
  class_id: string;
  table_id: string;
  bindings: MappingBinding[];
}
