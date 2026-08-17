import { Injectable, inject, signal } from '@angular/core';
import { ExtractionApi } from '../../../core/api/extraction.api';
import { SchemasApi } from '../../../core/api/schemas.api';
import { FilesApi } from '../../../core/api/files.api';
import { SchemaRead } from '../../../core/models/schema';
import { FileRead } from '../../../core/models/file';
import { BusinessLogicRuleRead, ExtractionTaskRead } from '../../../core/models/extraction';
import { ToastService } from '../../../core/services/toast.service';
import { switchMap, takeWhile, timer } from 'rxjs';

@Injectable()
export class BusinessLogicStore {
  private readonly extraction = inject(ExtractionApi);
  private readonly schemasApi = inject(SchemasApi);
  private readonly filesApi = inject(FilesApi);
  private readonly toast = inject(ToastService);

  readonly step = signal(1);
  readonly schemas = signal<SchemaRead[]>([]);
  readonly schemaId = signal('');
  readonly files = signal<FileRead[]>([]);
  readonly selectedFileIds = signal<Set<string>>(new Set());
  readonly task = signal<ExtractionTaskRead | null>(null);
  readonly rules = signal<BusinessLogicRuleRead[]>([]);

  bootstrap(): void {
    this.schemasApi.list({ page: 1, page_size: 100 }).subscribe({
      next: (r) => { this.schemas.set(r.items); if (r.items[0]) this.schemaId.set(r.items[0].id); },
    });
    this.filesApi.list({ status: 'ready', page: 1, page_size: 100 }).subscribe({
      next: (r) => this.files.set(r.items),
    });
  }

  toggleFile(id: string): void {
    const next = new Set(this.selectedFileIds());
    if (next.has(id)) next.delete(id); else next.add(id);
    this.selectedFileIds.set(next);
  }

  start(): void {
    this.step.set(3);
    this.extraction.startBusinessLogic({
      schema_id: this.schemaId(),
      file_ids: [...this.selectedFileIds()],
    }).subscribe({
      next: (t) => {
        timer(0, 400).pipe(
          switchMap(() => this.extraction.getTask(t.task_id)),
          takeWhile((x) => x.status === 'pending' || x.status === 'running', true),
        ).subscribe({
          next: (task) => {
            this.task.set(task);
            if (task.status === 'succeeded') {
              this.step.set(4);
              this.extraction.taskRules(t.task_id).subscribe({ next: (rules) => this.rules.set(rules) });
              this.toast.success('业务逻辑抽取完成');
            } else if (task.status === 'failed') {
              this.toast.error(task.error_message || '抽取失败');
            }
          },
        });
      },
    });
  }

  export(): void {
    this.extraction.exportRules(this.schemaId()).subscribe({
      next: (blob) => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'business-logic-rules.json';
        a.click();
        URL.revokeObjectURL(a.href);
      },
    });
  }

  jsonPreview(): string {
    return JSON.stringify(this.rules(), null, 2);
  }
}
