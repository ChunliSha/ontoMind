import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { PageResponse } from '../models/common';
import { QaChatResponse, QaSession, QaSessionSummary } from '../models/qa';

@Injectable({ providedIn: 'root' })
export class QaApi {
  private readonly api = inject(ApiClient);

  listSessions(params: {
    ontology_model_id?: string;
    page?: number;
    page_size?: number;
  }): Observable<PageResponse<QaSessionSummary>> {
    return this.api.get<PageResponse<QaSessionSummary>>('/ontology-apps/qa/sessions', params);
  }

  createSession(body: { ontology_model_id: string; model_id?: string | null }): Observable<QaSession> {
    return this.api.post<QaSession>('/ontology-apps/qa/sessions', body);
  }

  getSession(id: string): Observable<QaSession> {
    return this.api.get<QaSession>(`/ontology-apps/qa/sessions/${id}`);
  }

  updateSession(id: string, body: { title: string }): Observable<QaSession> {
    return this.api.patch<QaSession>(`/ontology-apps/qa/sessions/${id}`, body);
  }

  deleteSession(id: string): Observable<void> {
    return this.api.delete(`/ontology-apps/qa/sessions/${id}`);
  }

  sendMessage(sessionId: string, body: { question: string; model_id?: string | null }): Observable<QaChatResponse> {
    return this.api.post<QaChatResponse>(`/ontology-apps/qa/sessions/${sessionId}/messages`, body);
  }
}
