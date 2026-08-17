import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { PageResponse } from '../models/common';
import { BuildTableSqlResult, FilePreview, FileRead, FileUpdate, StorageBackend } from '../models/file';

@Injectable({ providedIn: 'root' })
export class FilesApi {
  private readonly api = inject(ApiClient);

  list(params?: {
    search?: string;
    file_type?: string;
    status?: string;
    storage_backend?: string;
    page?: number;
    page_size?: number;
  }): Observable<PageResponse<FileRead>> {
    return this.api.get<PageResponse<FileRead>>('/files', params);
  }

  upload(file: File, storageBackend: StorageBackend): Observable<FileRead> {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('storage_backend', storageBackend);
    return this.api.upload<FileRead>('/files', fd);
  }

  get(id: string): Observable<FileRead> {
    return this.api.get<FileRead>(`/files/${id}`);
  }

  preview(id: string): Observable<FilePreview> {
    return this.api.get<FilePreview>(`/files/${id}/preview`);
  }

  update(id: string, body: FileUpdate): Observable<FileRead> {
    return this.api.patch<FileRead>(`/files/${id}`, body);
  }

  convertStandardMd(id: string): Observable<FileRead> {
    return this.api.post<FileRead>(`/files/${id}/convert-standard-md`);
  }

  convertOntologyMd(id: string): Observable<FileRead> {
    return this.api.post<FileRead>(`/files/${id}/convert-ontology-md`);
  }

  buildTableSql(id: string): Observable<BuildTableSqlResult> {
    return this.api.post<BuildTableSqlResult>(`/files/${id}/build-table-sql`);
  }

  materializeTable(id: string, ddl?: string): Observable<{ table_id: string }> {
    return this.api.post<{ table_id: string }>(`/files/${id}/materialize-table`, { ddl });
  }

  remove(id: string): Observable<void> {
    return this.api.delete<void>(`/files/${id}`);
  }
}
