import { Injectable, inject, signal } from '@angular/core';
import { DashboardApi } from '../../core/api/dashboard.api';
import { ActivityItem, DashboardSummary } from '../../core/models/dashboard';

@Injectable()
export class DashboardStore {
  private readonly api = inject(DashboardApi);
  readonly summary = signal<DashboardSummary | null>(null);
  readonly activity = signal<ActivityItem[]>([]);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.summary().subscribe({
      next: (s) => { this.summary.set(s); this.loading.set(false); },
      error: () => { this.loading.set(false); this.error.set('加载统计失败'); },
    });
    this.api.activity().subscribe({
      next: (a) => {
        const items = Array.isArray(a) ? a : ((a as any).items ?? []);
        this.activity.set(items.map((x: any) => ({
          id: x.id,
          module: x.resource_type || 'system',
          text: x.text || x.action || '',
          color: x.color,
          created_at: x.created_at,
        })));
      },
      error: () => this.activity.set([]),
    });
  }
}
