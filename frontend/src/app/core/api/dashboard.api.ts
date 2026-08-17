import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiClient } from './api-client';
import { ActivityItem, DashboardSummary } from '../models/dashboard';

@Injectable({ providedIn: 'root' })
export class DashboardApi {
  private readonly api = inject(ApiClient);

  summary(): Observable<DashboardSummary> {
    return this.api.get<DashboardSummary>('/dashboard/summary');
  }

  activity(): Observable<ActivityItem[]> {
    return this.api.get<ActivityItem[]>('/dashboard/activity');
  }
}
