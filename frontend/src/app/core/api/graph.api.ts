import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { GraphMode, GraphNodeDetail, GraphResponse } from '../models/graph';

@Injectable({ providedIn: 'root' })
export class GraphApi {
  private readonly api = inject(ApiClient);

  getGraph(schemaId: string, mode: GraphMode, limit = 500): Observable<GraphResponse> {
    return this.api.get<GraphResponse>('/graph', { schema_id: schemaId, mode, limit });
  }

  nodeDetail(nodeId: string, nodeType: string): Observable<GraphNodeDetail> {
    return this.api.get<GraphNodeDetail>(`/graph/nodes/${nodeId}`, { node_type: nodeType });
  }
}
