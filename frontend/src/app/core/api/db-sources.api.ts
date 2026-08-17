import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { PageResponse } from '../models/common';
import {
  ConnectionTestResult,
  DbSourceCreate,
  DbSourceRead,
  DbSourceUpdate,
  DbTableRead,
} from '../models/db-source';

@Injectable({ providedIn: 'root' })
export class DbSourcesApi {
  private readonly api = inject(ApiClient);

  list(params?: {
    search?: string;
    db_type?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }): Observable<PageResponse<DbSourceRead>> {
    return this.api.get<PageResponse<DbSourceRead>>('/db-sources', params);
  }

  create(body: DbSourceCreate): Observable<DbSourceRead> {
    return this.api.post<DbSourceRead>('/db-sources', body);
  }

  update(id: string, body: DbSourceUpdate): Observable<DbSourceRead> {
    return this.api.patch<DbSourceRead>(`/db-sources/${id}`, body);
  }

  remove(id: string): Observable<void> {
    return this.api.delete<void>(`/db-sources/${id}`);
  }

  testConnection(id: string): Observable<ConnectionTestResult> {
    return this.api.post<ConnectionTestResult>(`/db-sources/${id}/test-connection`);
  }

  testDraft(body: DbSourceCreate): Observable<ConnectionTestResult> {
    return this.api.post<ConnectionTestResult>('/db-sources/test-connection', body);
  }

  tables(id: string): Observable<DbTableRead[]> {
    return this.api.get<DbTableRead[]>(`/db-sources/${id}/tables`);
  }

  selectTables(id: string, tableIds: string[]): Observable<DbTableRead[]> {
    return this.api.patch<DbTableRead[]>(`/db-sources/${id}/tables/selection`, {
      table_ids: tableIds,
    });
  }
}
