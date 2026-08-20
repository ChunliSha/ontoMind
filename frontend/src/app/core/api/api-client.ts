import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { SILENT_ERROR } from './silent-error';

// 使用 127.0.0.1 而非 localhost：Windows 上 localhost 常解析为 ::1，
// 而后端默认只监听 IPv4，会导致浏览器报「无法连接后端服务」。
export const API_BASE_URL = 'http://127.0.0.1:8000/api/v1';

@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);
  readonly baseUrl = API_BASE_URL;

  get<T>(
    path: string,
    params?: Record<string, string | number | boolean | undefined | null>,
    opts?: { silent?: boolean },
  ): Observable<T> {
    return this.http.get<T>(`${this.baseUrl}${path}`, {
      params: this.toParams(params),
      context: opts?.silent ? new HttpContext().set(SILENT_ERROR, true) : undefined,
    });
  }

  post<T>(path: string, body?: unknown): Observable<T> {
    return this.http.post<T>(`${this.baseUrl}${path}`, body ?? {});
  }

  patch<T>(path: string, body?: unknown): Observable<T> {
    return this.http.patch<T>(`${this.baseUrl}${path}`, body ?? {});
  }

  delete<T>(path: string): Observable<T> {
    return this.http.delete<T>(`${this.baseUrl}${path}`);
  }

  upload<T>(path: string, formData: FormData): Observable<T> {
    return this.http.post<T>(`${this.baseUrl}${path}`, formData);
  }

  getText(path: string, params?: Record<string, string | number | boolean | undefined | null>): Observable<string> {
    return this.http.get(`${this.baseUrl}${path}`, {
      params: this.toParams(params),
      responseType: 'text',
    });
  }

  getBlob(path: string, params?: Record<string, string | number | boolean | undefined | null>): Observable<Blob> {
    return this.http.get(`${this.baseUrl}${path}`, {
      params: this.toParams(params),
      responseType: 'blob',
    });
  }

  private toParams(params?: Record<string, string | number | boolean | undefined | null>): HttpParams {
    let httpParams = new HttpParams();
    if (!params) return httpParams;
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue;
      httpParams = httpParams.set(key, String(value));
    }
    return httpParams;
  }
}
