import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Observable, map } from 'rxjs';
import { SILENT_ERROR } from './silent-error';

function resolveApiBaseUrl(): string {
  // 本机用 127.0.0.1：Windows 上 localhost 常解析为 ::1，后端默认只听 IPv4。
  // 局域网用当前页面主机名，这样其他电脑打开 http://<本机IP>:4200 时会打到同一台机器的 :8000。
  const host =
    typeof window !== 'undefined' && window.location?.hostname
      ? window.location.hostname
      : '127.0.0.1';
  const apiHost = host === 'localhost' ? '127.0.0.1' : host;
  return `http://${apiHost}:8000/api/v1`;
}

export const API_BASE_URL = resolveApiBaseUrl();

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

  delete<T = void>(path: string): Observable<T> {
    return this.http.delete(`${this.baseUrl}${path}`, { responseType: 'text' }).pipe(
      map(() => undefined as T),
    );
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
