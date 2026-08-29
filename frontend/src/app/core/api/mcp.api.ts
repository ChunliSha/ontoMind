import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';

export interface McpTool {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export interface McpApiKey {
  id: string;
  name: string;
  key_prefix: string;
  created_at?: string | null;
  last_used_at?: string | null;
}

export interface McpApiKeyCreated extends McpApiKey {
  api_key: string;
}

export interface McpService {
  id: string;
  name: string;
  ontology_model_id?: string | null;
  ontology_model_name?: string | null;
  url: string;
  tool_names: string[];
  description: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface McpServiceCreate {
  name: string;
  ontology_model_id: string;
  url: string;
  tool_names: string[];
  description: string;
}

@Injectable({ providedIn: 'root' })
export class McpApi {
  private readonly api = inject(ApiClient);

  listTools(): Observable<{ tools: McpTool[] }> {
    return this.api.get<{ tools: McpTool[] }>('/mcp/tools');
  }

  listPublishedTools(): Observable<McpTool[]> {
    return this.api.get<McpTool[]>('/mcp/admin/tools');
  }

  listApiKeys(): Observable<McpApiKey[]> {
    return this.api.get<McpApiKey[]>('/mcp/api-keys');
  }

  createApiKey(body: { name?: string }): Observable<McpApiKeyCreated> {
    return this.api.post<McpApiKeyCreated>('/mcp/api-keys', body);
  }

  deleteApiKey(id: string): Observable<void> {
    return this.api.delete(`/mcp/api-keys/${id}`);
  }

  listServices(): Observable<McpService[]> {
    return this.api.get<McpService[]>('/mcp/services');
  }

  createService(body: McpServiceCreate): Observable<McpService> {
    return this.api.post<McpService>('/mcp/services', body);
  }

  updateService(id: string, body: Partial<McpServiceCreate>): Observable<McpService> {
    return this.api.patch<McpService>(`/mcp/services/${id}`, body);
  }

  deleteService(id: string): Observable<void> {
    return this.api.delete(`/mcp/services/${id}`);
  }
}
