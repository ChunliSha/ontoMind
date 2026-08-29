import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { KnowledgeAccessLog } from '../models/qa';
import { PageResponse } from '../models/common';
import { OntologyModelRead } from '../models/ontology-model';

@Injectable({ providedIn: 'root' })
export class KnowledgeApi {
  private readonly api = inject(ApiClient);

  listModels(params?: { page?: number; page_size?: number }): Observable<PageResponse<OntologyModelRead>> {
    return this.api.get<PageResponse<OntologyModelRead>>('/knowledge/models', params);
  }

  accessLogs(params?: { caller?: string; tool_name?: string; limit?: number }): Observable<KnowledgeAccessLog[]> {
    return this.api.get<KnowledgeAccessLog[]>('/knowledge/access-logs', params);
  }
}
