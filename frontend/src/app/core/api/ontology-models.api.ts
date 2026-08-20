import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { PageResponse } from '../models/common';
import { OntologyModelCreate, OntologyModelRead, OntologyModelUpdate } from '../models/ontology-model';

@Injectable({ providedIn: 'root' })
export class OntologyModelsApi {
  private readonly api = inject(ApiClient);

  list(params?: {
    schema_id?: string;
    search?: string;
    min_instances?: number;
    page?: number;
    page_size?: number;
  }): Observable<PageResponse<OntologyModelRead>> {
    return this.api.get<PageResponse<OntologyModelRead>>('/ontology-models', params);
  }

  get(id: string): Observable<OntologyModelRead> {
    return this.api.get<OntologyModelRead>(`/ontology-models/${id}`);
  }

  create(body: OntologyModelCreate): Observable<OntologyModelRead> {
    return this.api.post<OntologyModelRead>('/ontology-models', body);
  }

  update(id: string, body: OntologyModelUpdate): Observable<OntologyModelRead> {
    return this.api.patch<OntologyModelRead>(`/ontology-models/${id}`, body);
  }

  remove(id: string): Observable<void> {
    return this.api.delete<void>(`/ontology-models/${id}`);
  }
}
