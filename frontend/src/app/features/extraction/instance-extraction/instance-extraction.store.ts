import { Injectable, computed, inject, signal } from '@angular/core';
import { ExtractionApi } from '../../../core/api/extraction.api';
import { SchemasApi } from '../../../core/api/schemas.api';
import { FilesApi } from '../../../core/api/files.api';
import { MappingsApi } from '../../../core/api/mappings.api';
import { DbSourcesApi } from '../../../core/api/db-sources.api';
import { LlmModelsApi } from '../../../core/api/llm-models.api';
import { SchemaRead, ClassRead } from '../../../core/models/schema';
import { FileRead } from '../../../core/models/file';
import { LlmModelRead } from '../../../core/models/llm';
import {
  ExtractionTaskRead,
  InstanceDetail,
  InstanceInventory,
  InstanceRead,
  InstanceStat,
} from '../../../core/models/extraction';
import { MappingBinding, MappingRead, SourceField, TargetProperty } from '../../../core/models/mapping';
import { DbSourceRead, DbTableRead } from '../../../core/models/db-source';
import { ToastService } from '../../../core/services/toast.service';
import { switchMap, takeWhile, timer } from 'rxjs';

@Injectable()
export class InstanceExtractionStore {
  private readonly extraction = inject(ExtractionApi);
  private readonly schemasApi = inject(SchemasApi);
  private readonly filesApi = inject(FilesApi);
  private readonly mappingsApi = inject(MappingsApi);
  private readonly dbApi = inject(DbSourcesApi);
  private readonly llmApi = inject(LlmModelsApi);
  private readonly toast = inject(ToastService);

  readonly mode = signal<'unstruct' | 'struct'>('unstruct');
  readonly step = signal(1);
  readonly schemas = signal<SchemaRead[]>([]);
  readonly schemaId = signal<string>('');
  readonly classes = signal<ClassRead[]>([]);
  readonly files = signal<FileRead[]>([]);
  readonly selectedFileIds = signal<Set<string>>(new Set());
  readonly models = signal<LlmModelRead[]>([]);
  readonly selectedModelId = signal<string | null>(null);
  readonly replaceExisting = signal(true);
  readonly task = signal<ExtractionTaskRead | null>(null);
  readonly instances = signal<InstanceRead[]>([]);
  readonly stats = signal<InstanceStat[]>([]);
  readonly previewClassId = signal<string | null>(null);
  readonly instanceDetail = signal<InstanceDetail | null>(null);

  readonly filteredInstances = computed(() => {
    const classId = this.previewClassId();
    const rows = this.instances();
    if (!classId) return rows;
    return rows.filter((i) => i.class_id === classId);
  });

  readonly previewClassOptions = computed(() => {
    const fromStats = this.stats().filter((s) => s.count > 0);
    if (fromStats.length) {
      return fromStats.map((s) => ({ id: s.class_id, label: s.class_label, count: s.count }));
    }
    const map = new Map<string, { id: string; label: string; count: number }>();
    for (const i of this.instances()) {
      const cur = map.get(i.class_id);
      if (cur) cur.count += 1;
      else {
        map.set(i.class_id, {
          id: i.class_id,
          label: i.class_label || i.class_id.slice(0, 8),
          count: 1,
        });
      }
    }
    return [...map.values()].sort((a, b) => b.count - a.count);
  });

  readonly inventory = signal<InstanceInventory | null>(null);
  readonly inventoryVersion = signal<number | null>(null);
  readonly inventoryInstances = signal<InstanceRead[]>([]);
  readonly inventoryTotal = signal(0);

  readonly dbSources = signal<DbSourceRead[]>([]);
  readonly tables = signal<DbTableRead[]>([]);
  readonly selectedTableId = signal('');
  readonly selectedClassId = signal('');
  readonly sourceFields = signal<SourceField[]>([]);
  readonly targetProps = signal<TargetProperty[]>([]);
  readonly links = signal<{ source: string; target: string; targetKind: 'instance_uri' | 'property'; targetPropertyId?: string | null }[]>([]);
  readonly mappings = signal<MappingRead[]>([]);
  readonly selectedMappingIds = signal<Set<string>>(new Set());

  bootstrap(): void {
    this.schemasApi.list({ page: 1, page_size: 100 }).subscribe({
      next: (r) => {
        this.schemas.set(r.items.filter((s) => s.status === 'published').concat(r.items));
        if (r.items[0]) this.setSchema(r.items[0].id);
      },
    });
    this.filesApi.list({ status: 'ready', page: 1, page_size: 100 }).subscribe({
      next: (r) => this.files.set(r.items),
    });
    this.dbApi.list({ page: 1, page_size: 50 }).subscribe({
      next: (r) => this.dbSources.set(r.items),
    });
    this.llmApi.listActive().subscribe({
      next: (rows) => {
        this.models.set(rows);
        const def = rows.find((m) => m.is_default) ?? rows[0];
        if (def) this.selectedModelId.set(def.id);
      },
    });
  }

  currentSchema(): SchemaRead | undefined {
    return this.schemas().find((s) => s.id === this.schemaId());
  }

  setSchema(id: string): void {
    this.schemaId.set(id);
    const schema = this.schemas().find((s) => s.id === id);
    this.inventoryVersion.set(schema?.version ?? null);
    this.schemasApi.classes(id).subscribe({ next: (c) => this.classes.set(c) });
    this.mappingsApi.list({ schema_id: id }).subscribe({ next: (m) => this.mappings.set(m), error: () => this.mappings.set([]) });
    this.refreshInventory();
  }

  setInventoryVersion(version: number | null): void {
    this.inventoryVersion.set(version);
    this.refreshInventory();
  }

  refreshInventory(): void {
    const id = this.schemaId();
    if (!id) {
      this.inventory.set(null);
      this.inventoryInstances.set([]);
      this.inventoryTotal.set(0);
      return;
    }
    const ver = this.inventoryVersion();
    this.schemasApi.instanceInventory(id, ver).subscribe({
      next: (inv) => {
        this.inventory.set(inv);
        if (this.inventoryVersion() == null) this.inventoryVersion.set(inv.filter_version ?? inv.schema_version);
      },
      error: () => this.inventory.set(null),
    });
    this.schemasApi.listInstances(id, {
      schema_version: ver,
      page: 1,
      page_size: 100,
    }).subscribe({
      next: (r) => {
        this.inventoryInstances.set(r.items ?? []);
        this.inventoryTotal.set(r.total ?? 0);
      },
      error: () => {
        this.inventoryInstances.set([]);
        this.inventoryTotal.set(0);
      },
    });
  }

  clearInventory(sourceTypes?: string[] | null): void {
    const id = this.schemaId();
    if (!id) return;
    this.schemasApi.clearInstances(id, {
      schema_version: this.inventoryVersion(),
      source_types: sourceTypes ?? null,
    }).subscribe({
      next: (r) => {
        this.toast.success(`已清除 ${r.deleted} 条实例（Schema v${r.schema_version ?? '—'}）`);
        this.refreshInventory();
      },
    });
  }

  browseInventory(): void {
    const id = this.schemaId();
    if (!id) return;
    const ver = this.inventoryVersion();
    this.task.set(null);
    this.previewClassId.set(null);
    this.schemasApi.instanceInventory(id, ver).subscribe({
      next: (inv) => {
        this.inventory.set(inv);
        this.stats.set(inv.by_class ?? []);
      },
    });
    this.schemasApi.listInstances(id, {
      schema_version: ver,
      page: 1,
      page_size: 100,
    }).subscribe({
      next: (r) => {
        this.inventoryInstances.set(r.items ?? []);
        this.inventoryTotal.set(r.total ?? 0);
        this.instances.set(r.items ?? []);
        this.step.set(4);
      },
      error: () => this.toast.error('加载实例库失败'),
    });
  }

  setPreviewClassFilter(classId: string | null): void {
    this.previewClassId.set(classId || null);
  }

  togglePreviewClassFilter(classId: string): void {
    this.previewClassId.set(this.previewClassId() === classId ? null : classId);
  }

  toggleFile(id: string): void {
    const next = new Set(this.selectedFileIds());
    if (next.has(id)) next.delete(id); else next.add(id);
    this.selectedFileIds.set(next);
  }

  loadTables(sourceId: string): void {
    this.dbApi.tables(sourceId).subscribe({ next: (t) => this.tables.set(t.filter((x) => x.selected_for_modeling)) });
  }

  openMapping(tableId: string, classId: string): void {
    this.selectedTableId.set(tableId);
    this.selectedClassId.set(classId);
    this.mappingsApi.sourceFields(tableId).subscribe({ next: (f) => this.sourceFields.set(f) });
    this.mappingsApi.targetProperties(classId).subscribe({ next: (p) => this.targetProps.set(p) });
    this.links.set([]);
  }

  addLink(sourceCol: string, target: TargetProperty): void {
    const next = this.links().filter((l) => l.source !== sourceCol && !(target.kind === 'instance_uri' && l.targetKind === 'instance_uri'));
    next.push({
      source: sourceCol,
      target: target.id || '__uri__',
      targetKind: target.kind === 'instance_uri' ? 'instance_uri' : 'property',
      targetPropertyId: target.id,
    });
    this.links.set(next);
  }

  saveMapping(onDone?: () => void): void {
    const bindings: MappingBinding[] = this.links().map((l) => ({
      target_kind: l.targetKind,
      target_property_id: l.targetKind === 'property' ? l.targetPropertyId : null,
      source_column: l.source,
    }));
    this.mappingsApi.save({
      schema_id: this.schemaId(),
      class_id: this.selectedClassId(),
      table_id: this.selectedTableId(),
      bindings,
    }).subscribe({
      next: () => {
        this.toast.success('映射已保存');
        this.mappingsApi.list({ schema_id: this.schemaId() }).subscribe({ next: (m) => this.mappings.set(m) });
        onDone?.();
      },
    });
  }

  startUnstructured(): void {
    if (!this.selectedModelId()) {
      this.toast.error('请选择用于抽取的模型');
      return;
    }
    this.instances.set([]);
    this.stats.set([]);
    this.previewClassId.set(null);
    this.extraction.startUnstructured({
      schema_id: this.schemaId(),
      file_ids: [...this.selectedFileIds()],
      model_id: this.selectedModelId(),
      replace_existing: this.replaceExisting(),
    }).subscribe({ next: (t) => this.poll(t.task_id) });
  }

  startStructured(): void {
    this.extraction.startStructured({
      schema_id: this.schemaId(),
      mapping_ids: [...this.selectedMappingIds()],
    }).subscribe({ next: (t) => this.poll(t.task_id) });
  }

  private poll(taskId: string): void {
    this.step.set(3);
    timer(0, 400).pipe(
      switchMap(() => this.extraction.getTask(taskId)),
      takeWhile((t) => t.status === 'pending' || t.status === 'running', true),
    ).subscribe({
      next: (t) => {
        this.task.set(t);
        if (t.status === 'succeeded') {
          this.step.set(4);
          const summary = t.output_summary as { succeeded?: number; failed?: number; schema_version?: number } | null;
          const ok = summary?.succeeded ?? 0;
          const fail = summary?.failed ?? 0;
          if (summary?.schema_version != null) this.inventoryVersion.set(summary.schema_version);
          this.extraction.taskInstances(taskId, { page: 1, page_size: 200 }).subscribe({
            next: (r) => {
              const items = r.items ?? [];
              this.instances.set(items);
              const byClass = new Map<string, InstanceStat>();
              for (const i of items) {
                const cur = byClass.get(i.class_id);
                if (cur) cur.count += 1;
                else {
                  byClass.set(i.class_id, {
                    class_id: i.class_id,
                    class_label: i.class_label || i.class_id.slice(0, 8),
                    count: 1,
                  });
                }
              }
              this.stats.set([...byClass.values()].sort((a, b) => b.count - a.count));
              this.refreshInventory();
              if ((r.total ?? items.length) === 0) {
                this.toast.error(
                  fail > 0
                    ? `抽取完成但未写入实例（成功文件 ${ok}，失败 ${fail}）。请检查文档解析文本与 Schema 是否匹配。`
                    : '抽取完成但未写入实例。请检查文档内容与 Schema 类名是否可对齐。',
                );
              } else {
                this.toast.success(`抽取完成，共 ${r.total ?? items.length} 条实例`);
              }
            },
            error: () => this.toast.error('抽取完成，但加载结果预览失败'),
          });
        } else if (t.status === 'failed') {
          this.toast.error(t.error_message || '抽取失败');
        }
      },
    });
  }

  loadInstance(id: string): void {
    this.extraction.instanceDetail(id).subscribe({ next: (d) => this.instanceDetail.set(d) });
  }

  toggleMapping(id: string): void {
    const next = new Set(this.selectedMappingIds());
    if (next.has(id)) next.delete(id); else next.add(id);
    this.selectedMappingIds.set(next);
  }
}
