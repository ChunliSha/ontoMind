import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { PageResponse } from '../models/common';
import {
  LlmModelCreate,
  LlmModelRead,
  LlmModelTestResult,
  LlmModelUpdate,
  LlmPreset,
} from '../models/llm';

@Injectable({ providedIn: 'root' })
export class LlmModelsApi {
  private readonly api = inject(ApiClient);

  list(params?: {
    source?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }): Observable<PageResponse<LlmModelRead>> {
    return this.api.get<PageResponse<LlmModelRead>>('/llm-models', params);
  }

  listActive(): Observable<LlmModelRead[]> {
    return this.api.get<LlmModelRead[]>('/llm-models/active');
  }

  presets(): Observable<LlmPreset[]> {
    return this.api.get<LlmPreset[]>('/llm-models/presets');
  }

  create(body: LlmModelCreate): Observable<LlmModelRead> {
    return this.api.post<LlmModelRead>('/llm-models', body);
  }

  update(id: string, body: LlmModelUpdate): Observable<LlmModelRead> {
    return this.api.patch<LlmModelRead>(`/llm-models/${id}`, body);
  }

  remove(id: string): Observable<void> {
    return this.api.delete<void>(`/llm-models/${id}`);
  }

  test(id: string): Observable<LlmModelTestResult> {
    return this.api.post<LlmModelTestResult>(`/llm-models/${id}/test`);
  }

  setDefault(id: string): Observable<LlmModelRead> {
    return this.api.post<LlmModelRead>(`/llm-models/${id}/set-default`);
  }
}
