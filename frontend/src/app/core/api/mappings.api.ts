import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { MappingCreate, MappingRead, SourceField, TargetProperty } from '../models/mapping';

@Injectable({ providedIn: 'root' })
export class MappingsApi {
  private readonly api = inject(ApiClient);

  sourceFields(tableId: string): Observable<SourceField[]> {
    return this.api.get<SourceField[]>('/mappings/source-fields', { table_id: tableId });
  }

  targetProperties(classId: string): Observable<TargetProperty[]> {
    return this.api.get<TargetProperty[]>('/mappings/target-properties', { class_id: classId });
  }

  list(params: { schema_id?: string; class_id?: string }): Observable<MappingRead[]> {
    return this.api.get<MappingRead[]>('/mappings', params);
  }

  save(body: MappingCreate): Observable<MappingRead> {
    return this.api.post<MappingRead>('/mappings', body);
  }
}
