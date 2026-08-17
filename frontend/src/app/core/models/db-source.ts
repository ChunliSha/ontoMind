export type DbType = 'postgres' | 'mysql' | 'gaussdb';
export type DbSourceStatus = 'pending' | 'connected' | 'failed' | 'syncing';

export interface DbSourceRead {
  id: string;
  name: string;
  db_type: DbType;
  host: string;
  port: number;
  database_name: string;
  username: string;
  status: DbSourceStatus;
  last_error?: string | null;
  table_count: number;
  last_synced_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DbSourceCreate {
  name: string;
  db_type: DbType;
  host: string;
  port: number;
  database_name: string;
  username: string;
  password: string;
}

export interface DbSourceUpdate {
  name?: string;
  db_type?: DbType;
  host?: string;
  port?: number;
  database_name?: string;
  username?: string;
  password?: string;
}

export interface DbTableRead {
  id: string;
  data_source_id: string;
  table_schema: string;
  table_name: string;
  row_count?: number | null;
  column_count?: number | null;
  selected_for_modeling: boolean;
  is_generated: boolean;
}

export interface ConnectionTestResult {
  ok: boolean;
  message?: string;
  table_count?: number;
}
