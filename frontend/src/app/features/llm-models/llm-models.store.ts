import { Injectable, inject, signal } from '@angular/core';
import { LlmModelsApi } from '../../core/api/llm-models.api';
import {
  LlmModelCreate,
  LlmModelRead,
  LlmModelUpdate,
  LlmPreset,
} from '../../core/models/llm';
import { ToastService } from '../../core/services/toast.service';

@Injectable()
export class LlmModelsStore {
  private readonly api = inject(LlmModelsApi);
  private readonly toast = inject(ToastService);

  readonly items = signal<LlmModelRead[]>([]);
  readonly presets = signal<LlmPreset[]>([]);
  readonly loading = signal(false);
  readonly sourceFilter = signal<string>('');

  load(): void {
    this.loading.set(true);
    this.api.list({
      source: this.sourceFilter() || undefined,
      page: 1,
      page_size: 100,
    }).subscribe({
      next: (r) => { this.items.set(r.items); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  loadPresets(): void {
    this.api.presets().subscribe({ next: (p) => this.presets.set(p) });
  }

  create(body: LlmModelCreate, onDone?: () => void): void {
    this.api.create(body).subscribe({
      next: () => { this.toast.success('模型已添加'); this.load(); onDone?.(); },
    });
  }

  update(id: string, body: LlmModelUpdate, onDone?: () => void): void {
    this.api.update(id, body).subscribe({
      next: () => { this.toast.success('模型已更新'); this.load(); onDone?.(); },
    });
  }

  remove(id: string): void {
    this.api.remove(id).subscribe({
      next: () => { this.toast.success('已删除'); this.load(); },
    });
  }

  test(id: string): void {
    this.api.test(id).subscribe({
      next: (r) => {
        if (r.ok) this.toast.success(r.message + (r.latency_ms != null ? `（${r.latency_ms}ms）` : ''));
        else this.toast.error(r.message);
        this.load();
      },
    });
  }

  setDefault(id: string): void {
    this.api.setDefault(id).subscribe({
      next: () => { this.toast.success('已设为默认模型'); this.load(); },
    });
  }
}
