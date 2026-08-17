import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { ApiClient } from './api-client';
import { PageResponse, TaskCreated } from '../models/common';
import {
  BusinessLogicExtractionRequest,
  BusinessLogicRuleRead,
  ExtractionTaskRead,
  InstanceDetail,
  InstanceRead,
  InstanceStat,
  InstanceStatsResponse,
  StructuredExtractionRequest,
  UnstructuredExtractionRequest,
} from '../models/extraction';

@Injectable({ providedIn: 'root' })
export class ExtractionApi {
  private readonly api = inject(ApiClient);

  startUnstructured(body: UnstructuredExtractionRequest): Observable<TaskCreated> {
    return this.api.post<TaskCreated>('/extraction/instances/unstructured', body);
  }

  startStructured(body: StructuredExtractionRequest): Observable<TaskCreated> {
    return this.api.post<TaskCreated>('/extraction/instances/structured', body);
  }

  startBusinessLogic(body: BusinessLogicExtractionRequest): Observable<TaskCreated> {
    return this.api.post<TaskCreated>('/extraction/business-logic', body);
  }

  getTask(id: string): Observable<ExtractionTaskRead> {
    return this.api.get<ExtractionTaskRead>(`/extraction/tasks/${id}`);
  }

  taskInstances(
    taskId: string,
    params?: { page?: number; page_size?: number },
  ): Observable<PageResponse<InstanceRead>> {
    return this.api.get<PageResponse<InstanceRead>>(`/extraction/tasks/${taskId}/instances`, params);
  }

  taskRules(taskId: string): Observable<BusinessLogicRuleRead[]> {
    return this.api.get<BusinessLogicRuleRead[]>(`/extraction/tasks/${taskId}/rules`);
  }

  instanceDetail(id: string): Observable<InstanceDetail> {
    return this.api.get<InstanceDetail>(`/instances/${id}`);
  }

  instanceStats(schemaId: string): Observable<InstanceStat[]> {
    return this.api
      .get<InstanceStatsResponse>(`/schemas/${schemaId}/instance-stats`)
      .pipe(map((r) => r.by_class ?? []));
  }

  listRules(schemaId: string): Observable<BusinessLogicRuleRead[]> {
    return this.api.get<BusinessLogicRuleRead[]>('/business-logic-rules', { schema_id: schemaId });
  }

  exportRules(schemaId: string): Observable<Blob> {
    return this.api.getBlob('/business-logic-rules/export', { schema_id: schemaId, format: 'json' });
  }
}
