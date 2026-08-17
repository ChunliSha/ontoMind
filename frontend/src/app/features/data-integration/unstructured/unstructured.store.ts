import { Injectable, inject, signal } from '@angular/core';
import { FilesApi } from '../../../core/api/files.api';
import { FileRead, StorageBackend } from '../../../core/models/file';
import { ToastService } from '../../../core/services/toast.service';

@Injectable()
export class UnstructuredStore {
  private readonly api = inject(FilesApi);
  private readonly toast = inject(ToastService);
  readonly items = signal<FileRead[]>([]);
  readonly loading = signal(false);
  readonly search = signal('');
  readonly storageBackend = signal<StorageBackend>('local');

  load(): void {
    this.loading.set(true);
    this.api.list({ search: this.search(), page: 1, page_size: 100 }).subscribe({
      next: (r) => { this.items.set(r.items); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  upload(files: File[]): void {
    files.forEach((f) => {
      this.api.upload(f, this.storageBackend()).subscribe({
        next: () => { this.toast.success(`已上传 ${f.name}`); this.load(); },
      });
    });
  }

  convertMd(id: string, ontology = false): void {
    const obs = ontology ? this.api.convertOntologyMd(id) : this.api.convertStandardMd(id);
    obs.subscribe({ next: () => { this.toast.success(ontology ? '已转本体 MD' : '已转标准 MD'); this.load(); } });
  }

  rename(id: string, name: string): void {
    this.api.update(id, { name }).subscribe({ next: () => { this.toast.success('已重命名'); this.load(); } });
  }

  updateText(id: string, extracted_text: string): void {
    this.api.update(id, { extracted_text }).subscribe({ next: () => { this.toast.success('已保存'); this.load(); } });
  }

  remove(id: string): void {
    this.api.remove(id).subscribe({ next: () => { this.toast.success('已删除'); this.load(); } });
  }
}
