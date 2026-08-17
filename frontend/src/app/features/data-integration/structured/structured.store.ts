import { Injectable, inject, signal } from '@angular/core';
import { DbSourcesApi } from '../../../core/api/db-sources.api';
import { DbSourceCreate, DbSourceRead, DbSourceUpdate, DbTableRead } from '../../../core/models/db-source';
import { ToastService } from '../../../core/services/toast.service';

@Injectable()
export class StructuredStore {
  private readonly api = inject(DbSourcesApi);
  private readonly toast = inject(ToastService);

  readonly items = signal<DbSourceRead[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly search = signal('');
  readonly tables = signal<DbTableRead[]>([]);
  readonly activeSource = signal<DbSourceRead | null>(null);

  load(): void {
    this.loading.set(true);
    this.api.list({ search: this.search(), page: 1, page_size: 50 }).subscribe({
      next: (res) => { this.items.set(res.items); this.total.set(res.total); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  create(body: DbSourceCreate, onDone?: () => void): void {
    this.api.create(body).subscribe({
      next: () => { this.toast.success('数据库连接已创建'); this.load(); onDone?.(); },
    });
  }

  update(id: string, body: DbSourceUpdate, onDone?: () => void): void {
    this.api.update(id, body).subscribe({
      next: () => { this.toast.success('连接已更新'); this.load(); onDone?.(); },
    });
  }

  remove(id: string): void {
    this.api.remove(id).subscribe({
      next: () => { this.toast.success('已删除'); this.load(); },
    });
  }

  retry(id: string): void {
    this.api.testConnection(id).subscribe({
      next: (r) => { this.toast.success(r.ok ? '连接成功' : (r.message || '连接失败')); this.load(); },
    });
  }

  loadTables(source: DbSourceRead): void {
    this.activeSource.set(source);
    this.api.tables(source.id).subscribe({ next: (t) => this.tables.set(t) });
  }

  saveTableSelection(tableIds: string[], onDone?: () => void): void {
    const src = this.activeSource();
    if (!src) return;
    this.api.selectTables(src.id, tableIds).subscribe({
      next: () => { this.toast.success('表选择已保存'); this.load(); onDone?.(); },
    });
  }
}
