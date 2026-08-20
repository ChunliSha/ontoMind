import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import {
  InstanceCatalogResponse,
  NodeTypeRead,
  TopologyPatchRequest,
  TopologyRead,
  TopologySummary,
  TypeMappingSuggestResponse,
} from '../models/topology';

@Injectable({ providedIn: 'root' })
export class TopologyApi {
  private readonly api = inject(ApiClient);

  nodeTypes(): Observable<NodeTypeRead[]> {
    return this.api.get<NodeTypeRead[]>('/business-logic/node-types');
  }

  suggestTypeMapping(schemaId: string, schemaVersion?: number | null): Observable<TypeMappingSuggestResponse> {
    return this.api.get<TypeMappingSuggestResponse>('/business-logic/type-mapping/suggest', {
      schema_id: schemaId,
      schema_version: schemaVersion ?? undefined,
    });
  }

  instanceCatalog(schemaId: string, schemaVersion?: number | null): Observable<InstanceCatalogResponse> {
    return this.api.get<InstanceCatalogResponse>('/business-logic/instance-catalog', {
      schema_id: schemaId,
      schema_version: schemaVersion ?? undefined,
    });
  }

  list(schemaId?: string, schemaVersion?: number | null, ontologyModelId?: string | null): Observable<TopologySummary[]> {
    return this.api.get<TopologySummary[]>('/business-logic/topologies', {
      schema_id: schemaId,
      schema_version: schemaVersion ?? undefined,
      ontology_model_id: ontologyModelId ?? undefined,
    });
  }

  get(id: string): Observable<TopologyRead> {
    return this.api.get<TopologyRead>(`/business-logic/topologies/${id}`);
  }

  patch(id: string, body: TopologyPatchRequest): Observable<TopologyRead> {
    return this.api.patch<TopologyRead>(`/business-logic/topologies/${id}`, body);
  }

  remove(id: string): Observable<void> {
    return this.api.delete<void>(`/business-logic/topologies/${id}`);
  }

  export(id: string): Observable<Blob> {
    return this.api.getBlob(`/business-logic/topologies/${id}/export`);
  }

  byTask(taskId: string): Observable<TopologyRead> {
    return this.api.get<TopologyRead>(`/extraction/tasks/${taskId}/topology`);
  }
}
