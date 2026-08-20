export interface OntologyModelRead {
  id: string;
  name: string;
  description: string;
  schema_id: string;
  schema_name: string;
  schema_version: number;
  class_count: number;
  instance_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface OntologyModelCreate {
  name: string;
  description?: string;
  schema_id: string;
  schema_version?: number | null;
}

export interface OntologyModelUpdate {
  name?: string;
  description?: string;
}
