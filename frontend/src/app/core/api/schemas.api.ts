import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { PageResponse, TaskCreated } from '../models/common';
import {
  ClearInstancesResult,
  InstanceInventory,
  InstanceRead,
} from '../models/extraction';
import {
  ClassCreate,
  ClassRead,
  PropertyCreate,
  PropertyRead,
  SchemaCreate,
  SchemaPublishRequest,
  SchemaRead,
} from '../models/schema';

@Injectable({ providedIn: 'root' })
export class SchemasApi {
  private readonly api = inject(ApiClient);

  list(params?: { search?: string; page?: number; page_size?: number }): Observable<PageResponse<SchemaRead>> {
    return this.api.get<PageResponse<SchemaRead>>('/schemas', params);
  }

  create(body: SchemaCreate): Observable<SchemaRead> {
    return this.api.post<SchemaRead>('/schemas', body);
  }

  get(id: string): Observable<SchemaRead> {
    return this.api.get<SchemaRead>(`/schemas/${id}`);
  }

  update(id: string, body: Partial<SchemaCreate>): Observable<SchemaRead> {
    return this.api.patch<SchemaRead>(`/schemas/${id}`, body);
  }

  publish(id: string, body: SchemaPublishRequest = {}): Observable<SchemaRead> {
    return this.api.post<SchemaRead>(`/schemas/${id}/publish`, body);
  }

  remove(id: string): Observable<void> {
    return this.api.delete<void>(`/schemas/${id}`);
  }

  classes(schemaId: string): Observable<ClassRead[]> {
    return this.api.get<ClassRead[]>(`/schemas/${schemaId}/classes`);
  }

  createClass(schemaId: string, body: ClassCreate): Observable<ClassRead> {
    return this.api.post<ClassRead>(`/schemas/${schemaId}/classes`, body);
  }

  updateClass(classId: string, body: Partial<ClassCreate>): Observable<ClassRead> {
    return this.api.patch<ClassRead>(`/classes/${classId}`, body);
  }

  deleteClass(classId: string): Observable<void> {
    return this.api.delete<void>(`/classes/${classId}`);
  }

  properties(classId: string): Observable<PropertyRead[]> {
    return this.api.get<PropertyRead[]>(`/classes/${classId}/properties`);
  }

  schemaProperties(schemaId: string): Observable<PropertyRead[]> {
    return this.api.get<PropertyRead[]>(`/schemas/${schemaId}/properties`);
  }

  createProperty(classId: string, body: PropertyCreate): Observable<PropertyRead> {
    return this.api.post<PropertyRead>(`/classes/${classId}/properties`, body);
  }

  updateProperty(propertyId: string, body: Partial<PropertyCreate & { domain_class_id?: string }>): Observable<PropertyRead> {
    return this.api.patch<PropertyRead>(`/properties/${propertyId}`, body);
  }

  deleteProperty(propertyId: string): Observable<void> {
    return this.api.delete<void>(`/properties/${propertyId}`);
  }

  induce(schemaId: string, body?: { file_ids?: string[]; model_id?: string | null }): Observable<TaskCreated> {
    return this.api.post<TaskCreated>(`/schemas/${schemaId}/induce`, body ?? {});
  }

  exportTtl(
    schemaId: string,
    opts?: { include_instances?: boolean; schema_version?: number | null },
  ): Observable<string> {
    return this.api.getText(`/schemas/${schemaId}/export-ttl`, {
      include_instances: opts?.include_instances ?? false,
      schema_version: opts?.schema_version ?? undefined,
    });
  }

  importTtl(file: File): Observable<SchemaRead> {
    const fd = new FormData();
    fd.append('file', file);
    return this.api.upload<SchemaRead>('/schemas/import-ttl', fd);
  }

  instanceInventory(schemaId: string, schemaVersion?: number | null): Observable<InstanceInventory> {
    return this.api.get<InstanceInventory>(`/schemas/${schemaId}/instance-inventory`, {
      schema_version: schemaVersion ?? undefined,
    });
  }

  listInstances(
    schemaId: string,
    params?: {
      schema_version?: number | null;
      class_id?: string;
      source_type?: string;
      page?: number;
      page_size?: number;
    },
  ): Observable<PageResponse<InstanceRead>> {
    return this.api.get<PageResponse<InstanceRead>>(`/schemas/${schemaId}/instances`, params);
  }

  clearInstances(
    schemaId: string,
    body?: { schema_version?: number | null; source_types?: string[] | null },
  ): Observable<ClearInstancesResult> {
    return this.api.post<ClearInstancesResult>(`/schemas/${schemaId}/instances/clear`, body ?? {});
  }
}
