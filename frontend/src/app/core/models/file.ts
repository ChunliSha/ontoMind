export type StorageBackend = 'local' | 'minio';
export type FileStatus = 'pending' | 'parsing' | 'ready' | 'failed';

export interface FileRead {
  id: string;
  name: string;
  file_type: string;
  storage_backend: StorageBackend;
  size_bytes: number;
  status: FileStatus;
  error_message?: string | null;
  standard_md_path?: string | null;
  ontology_md_path?: string | null;
  extracted_text?: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileUpdate {
  name?: string;
  extracted_text?: string;
}

export interface FilePreview {
  text: string;
  truncated: boolean;
}

export interface BuildTableSqlResult {
  ddl: string;
  table_name: string;
  columns: { name: string; data_type: string }[];
}
