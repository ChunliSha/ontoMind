import { Injectable, computed, inject, signal } from '@angular/core';
import { SchemasApi } from '../../core/api/schemas.api';
import { ExtractionApi } from '../../core/api/extraction.api';
import { FilesApi } from '../../core/api/files.api';
import { LlmModelsApi } from '../../core/api/llm-models.api';
import { ClassCreate, ClassRead, PropertyCreate, PropertyRead, SchemaRead } from '../../core/models/schema';
import { FileRead } from '../../core/models/file';
import { LlmModelRead } from '../../core/models/llm';
import { ToastService } from '../../core/services/toast.service';
import { switchMap, takeWhile, timer } from 'rxjs';

@Injectable()
export class SchemaStudioStore {
  private readonly api = inject(SchemasApi);
  private readonly extraction = inject(ExtractionApi);
  private readonly filesApi = inject(FilesApi);
  private readonly llmApi = inject(LlmModelsApi);
  private readonly toast = inject(ToastService);

  readonly schemas = signal<SchemaRead[]>([]);
  readonly current = signal<SchemaRead | null>(null);
  readonly classes = signal<ClassRead[]>([]);
  readonly selectedClassId = signal<string | null>(null);
  readonly properties = signal<PropertyRead[]>([]);
  readonly loading = signal(false);
  readonly extracting = signal(false);
  readonly statusText = signal('状态：待抽取');

  readonly sourceFiles = signal<FileRead[]>([]);
  readonly selectedFileIds = signal<Set<string>>(new Set());
  readonly models = signal<LlmModelRead[]>([]);
  readonly selectedModelId = signal<string | null>(null);

  readonly selectedFileCount = computed(() => this.selectedFileIds().size);

  loadSchemas(selectId?: string): void {
    this.loading.set(true);
    this.api.list({ page: 1, page_size: 100 }).subscribe({
      next: (r) => {
        this.schemas.set(r.items);
        this.loading.set(false);
        const pick = selectId ? r.items.find((s) => s.id === selectId) : (this.current() ?? r.items[0]);
        if (pick) this.selectSchema(pick.id);
        else { this.current.set(null); this.classes.set([]); this.properties.set([]); }
      },
      error: () => this.loading.set(false),
    });
  }

  loadSourceFiles(): void {
    this.filesApi.list({ page: 1, page_size: 100 }).subscribe({
      next: (r) => {
        this.sourceFiles.set(r.items);
        const ready = new Set(r.items.filter((f) => f.status === 'ready').map((f) => f.id));
        this.selectedFileIds.set(ready);
      },
    });
  }

  loadModels(): void {
    this.llmApi.listActive().subscribe({
      next: (rows) => {
        this.models.set(rows);
        const def = rows.find((m) => m.is_default) ?? rows[0];
        if (def && !this.selectedModelId()) this.selectedModelId.set(def.id);
      },
    });
  }

  toggleFile(id: string, checked: boolean): void {
    const next = new Set(this.selectedFileIds());
    if (checked) next.add(id);
    else next.delete(id);
    this.selectedFileIds.set(next);
  }

  selectSchema(id: string): void {
    this.api.get(id).subscribe({
      next: (s) => {
        this.current.set(s);
        // 工作区与 Schema 管理共用同一列表：同步名称/计数，保证一一对应
        this.schemas.update((list) => {
          const exists = list.some((x) => x.id === s.id);
          if (!exists) return [s, ...list];
          return list.map((x) => (x.id === s.id ? { ...x, ...s } : x));
        });
        this.statusText.set(
          s.status === 'published'
            ? `状态：已发布 · ${s.name}`
            : `状态：可编辑 · ${s.name}`,
        );
        this.api.classes(id).subscribe({
          next: (cs) => {
            this.classes.set(cs);
            const first = cs[0];
            if (first) this.selectClass(first.id);
            else { this.selectedClassId.set(null); this.properties.set([]); }
          },
        });
      },
    });
  }

  selectClass(id: string): void {
    this.selectedClassId.set(id);
    this.api.properties(id).subscribe({ next: (ps) => this.properties.set(ps) });
  }

  createSchema(name: string, onDone?: (s: SchemaRead) => void): void {
    this.api.create({ name }).subscribe({
      next: (s) => {
        this.toast.success('Schema 已创建');
        this.loadSchemas(s.id);
        onDone?.(s);
      },
    });
  }

  renameSchema(id: string, name: string, onDone?: () => void): void {
    const trimmed = name.trim();
    if (!trimmed) {
      this.toast.error('请输入 Schema 名称');
      return;
    }
    this.api.update(id, { name: trimmed }).subscribe({
      next: () => {
        this.toast.success('名称已更新');
        this.loadSchemas(id);
        onDone?.();
      },
    });
  }

  addClass(body: ClassCreate): void {
    const s = this.current();
    if (!s) return;
    this.api.createClass(s.id, body).subscribe({
      next: (c) => { this.toast.success('类已添加'); this.selectSchema(s.id); this.selectClass(c.id); },
    });
  }

  addProperty(body: PropertyCreate): void {
    const cid = this.selectedClassId();
    if (!cid) return;
    this.api.createProperty(cid, body).subscribe({
      next: () => { this.toast.success('属性已添加'); this.selectClass(cid); this.refreshCurrent(); },
    });
  }

  updateProperty(id: string, body: Partial<PropertyCreate>): void {
    const cid = this.selectedClassId();
    this.api.updateProperty(id, body).subscribe({
      next: () => { this.toast.success('属性已更新'); if (cid) this.selectClass(cid); },
    });
  }

  deleteProperty(id: string): void {
    const cid = this.selectedClassId();
    this.api.deleteProperty(id).subscribe({
      next: () => { this.toast.success('属性已删除'); if (cid) this.selectClass(cid); this.refreshCurrent(); },
    });
  }

  deleteClass(id: string): void {
    const s = this.current();
    this.api.deleteClass(id).subscribe({
      next: () => { this.toast.success('类已删除'); if (s) this.selectSchema(s.id); },
    });
  }

  deleteSchema(id: string): void {
    this.api.remove(id).subscribe({
      next: () => { this.toast.success('Schema 已删除'); this.current.set(null); this.loadSchemas(); },
    });
  }

  publish(changeLog?: string): void {
    const s = this.current();
    if (!s) return;
    this.api.publish(s.id, { change_log: changeLog }).subscribe({
      next: () => { this.toast.success('已发布'); this.loadSchemas(s.id); },
    });
  }

  /**
   * 开始 Schema 抽取。
   * - createNew=true：先按自定义名称新建 Schema，再写入抽取结果
   * - 否则写入当前 Schema，并可在抽取前更新名称
   */
  startExtract(options?: { name?: string; createNew?: boolean }): void {
    const fileIds = [...this.selectedFileIds()];
    if (!fileIds.length) {
      this.toast.error('请先选择至少一个已解析完成的文档');
      return;
    }
    const readyIds = fileIds.filter((id) => this.sourceFiles().find((f) => f.id === id)?.status === 'ready');
    if (!readyIds.length) {
      this.toast.error('请先选择至少一个已解析完成的文档');
      return;
    }
    if (!this.selectedModelId()) {
      this.toast.error('请选择用于抽取的模型');
      return;
    }

    const desiredName = (options?.name || '').trim();
    if (!desiredName) {
      this.toast.error('请填写 Schema 名称');
      return;
    }

    const beginInduce = (schemaId: string) => {
      this.extracting.set(true);
      this.statusText.set('状态：抽取中…');
      this.api.induce(schemaId, { file_ids: readyIds, model_id: this.selectedModelId() }).subscribe({
        next: (t) => {
          timer(0, 400).pipe(
            switchMap(() => this.extraction.getTask(t.task_id)),
            takeWhile((task) => task.status === 'pending' || task.status === 'running', true),
          ).subscribe({
            next: (task) => {
              if (task.status === 'succeeded') {
                this.extracting.set(false);
                const created = Number(task.output_summary?.['classes_created'] ?? 0);
                if (created <= 0) {
                  this.toast.error('抽取完成但未生成新类，请检查文档内容或模型输出');
                } else {
                  this.toast.success(`Schema 抽取完成（新增 ${created} 个类）`);
                }
                this.loadSchemas(schemaId);
              } else if (task.status === 'failed') {
                this.extracting.set(false);
                this.statusText.set('状态：抽取失败');
                this.toast.error(task.error_message || '抽取失败');
              }
            },
            error: () => {
              this.extracting.set(false);
              this.statusText.set('状态：可编辑');
            },
          });
        },
        error: () => {
          this.extracting.set(false);
          this.statusText.set('状态：可编辑');
        },
      });
    };

    if (options?.createNew) {
      this.api.create({ name: desiredName }).subscribe({
        next: (created) => {
          this.toast.success(`已新建 Schema「${desiredName}」`);
          beginInduce(created.id);
        },
      });
      return;
    }

    const s = this.current();
    if (!s) {
      this.toast.error('请先选择或新建 Schema');
      return;
    }

    if (desiredName !== s.name) {
      this.api.update(s.id, { name: desiredName }).subscribe({
        next: () => beginInduce(s.id),
        error: () => beginInduce(s.id),
      });
    } else {
      beginInduce(s.id);
    }
  }

  exportTtl(): void {
    const s = this.current();
    if (!s) return;
    this.api.exportTtl(s.id).subscribe({
      next: (ttl) => {
        const blob = new Blob([ttl], { type: 'text/turtle' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${s.name}.ttl`;
        a.click();
        URL.revokeObjectURL(a.href);
        this.toast.success('TTL 已导出');
      },
    });
  }

  importTtl(file: File): void {
    this.api.importTtl(file).subscribe({
      next: (s) => { this.toast.success('TTL 导入成功'); this.loadSchemas(s.id); },
    });
  }

  private refreshCurrent(): void {
    const s = this.current();
    if (s) this.selectSchema(s.id);
  }

  /** 与 Schema 管理页共用刷新，保持名称与统计一致 */
  reloadListKeepingSelection(): void {
    this.loadSchemas(this.current()?.id);
  }

  suggestedExtractName(): string {
    const p = (n: number) => String(n).padStart(2, '0');
    const d = new Date();
    return `抽取结果 · ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
}
