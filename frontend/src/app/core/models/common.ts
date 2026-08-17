export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ErrorDetail {
  code: string;
  message: string;
  field?: string | null;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

export interface TaskCreated {
  task_id: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
}
