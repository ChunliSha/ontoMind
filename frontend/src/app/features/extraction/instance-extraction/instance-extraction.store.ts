import { Injectable, NgZone, OnDestroy, computed, inject, signal } from '@angular/core';
import { ExtractionApi } from '../../../core/api/extraction.api';
import { SchemasApi } from '../../../core/api/schemas.api';
import { FilesApi } from '../../../core/api/files.api';
import { MappingsApi } from '../../../core/api/mappings.api';
import { DbSourcesApi } from '../../../core/api/db-sources.api';
import { LlmModelsApi } from '../../../core/api/llm-models.api';
import { OntologyModelsApi } from '../../../core/api/ontology-models.api';
import { SchemaRead, ClassRead } from '../../../core/models/schema';
import { FileRead } from '../../../core/models/file';
import { LlmModelRead } from '../../../core/models/llm';
import { OntologyModelCreate, OntologyModelRead, OntologyModelUpdate } from '../../../core/models/ontology-model';
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
import { Subscription, catchError, filter, of, switchMap, timer } from 'rxjs';

type PreviewView = 'unstruct' | 'struct' | 'merged';

interface PreviewBucket {
  task: ExtractionTaskRead | null;
  instances: InstanceRead[];
  stats: InstanceStat[];
}

function emptyPreview(): PreviewBucket {
  return { task: null, instances: [], stats: [] };
}

function statsFromInstances(items: InstanceRead[]): InstanceStat[] {
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
  return [...byClass.values()].sort((a, b) => b.count - a.count);
}

@Injectable()
export class InstanceExtractionStore implements OnDestroy {
  private readonly extraction = inject(ExtractionApi);
  private readonly schemasApi = inject(SchemasApi);
  private readonly filesApi = inject(FilesApi);
  private readonly mappingsApi = inject(MappingsApi);
  private readonly dbApi = inject(DbSourcesApi);
  private readonly llmApi = inject(LlmModelsApi);
  private readonly ontoApi = inject(OntologyModelsApi);
  private readonly toast = inject(ToastService);
  private readonly zone = inject(NgZone);

  readonly mode = signal<'unstruct' | 'struct' | 'models'>('unstruct');
  readonly step = signal(1);
  /** Highest step the user has reached in this session (for done styling). */
  readonly maxReachedStep = signal(1);
  readonly stepLabels = ['选择 Schema', '选择数据', '执行抽取', '结果预览'] as const;
  readonly schemas = signal<SchemaRead[]>([]);
  readonly schemaId = signal<string>('');
  readonly classes = signal<ClassRead[]>([]);
  readonly files = signal<FileRead[]>([]);
  readonly selectedFileIds = signal<Set<string>>(new Set());
  readonly models = signal<LlmModelRead[]>([]);
  readonly selectedModelId = signal<string | null>(null);
  readonly replaceExisting = signal(true);
  readonly cancelling = signal(false);
  /** In-flight / last polled task (step 3 progress). */
  readonly task = signal<ExtractionTaskRead | null>(null);
  readonly taskProgress = computed(() => {
    const raw = this.task()?.progress as number | string | null | undefined;
    const n = typeof raw === 'string' ? parseFloat(raw) : Number(raw ?? 0);
    return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
  });
  readonly taskStage = computed(() => {
    const t = this.task();
    if (!t) return '';
    const stage = t.output_summary?.['stage'];
    if (typeof stage === 'string' && stage.trim()) return stage;
    if (t.status === 'pending') return '正在启动抽取…';
    if (t.status === 'running') return '正在抽取（模型需依次做实体、关系、三元组，请稍候）';
    if (t.status === 'succeeded') return '抽取完成';
    if (t.status === 'failed') return t.error_message || '抽取失败';
    return t.status || '';
  });
  /**
   * Result preview scope:
   * - unstruct / struct: that submodule only
   * - merged: combined preview of both source types
   */
  readonly previewView = signal<PreviewView>('unstruct');
  readonly unstructPreview = signal<PreviewBucket>(emptyPreview());
  readonly structPreview = signal<PreviewBucket>(emptyPreview());
  readonly mergedPreview = signal<PreviewBucket>(emptyPreview());
  readonly previewClassId = signal<string | null>(null);
  readonly instanceDetail = signal<InstanceDetail | null>(null);

  readonly activePreview = computed(() => {
    const v = this.previewView();
    if (v === 'merged') return this.mergedPreview();
    if (v === 'struct') return this.structPreview();
    return this.unstructPreview();
  });
  readonly instances = computed(() => this.activePreview().instances);
  readonly stats = computed(() => this.activePreview().stats);
  readonly previewTask = computed(() => this.activePreview().task);

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

  readonly previewTitle = computed(() => {
    const v = this.previewView();
    if (v === 'merged') return '合并预览（非结构化 + 结构化）';
    if (v === 'struct') return '结构化抽取结果预览';
    return '非结构化抽取结果预览';
  });

  readonly inventory = signal<InstanceInventory | null>(null);
  readonly inventoryVersion = signal<number | null>(null);
  readonly inventoryInstances = signal<InstanceRead[]>([]);
  readonly inventoryTotal = signal(0);

  readonly dbSources = signal<DbSourceRead[]>([]);
  readonly tables = signal<DbTableRead[]>([]);
  readonly selectedDbSourceId = signal('');
  readonly tablesLoading = signal(false);
  readonly selectedTableId = signal('');
  readonly selectedClassId = signal('');
  readonly sourceFields = signal<SourceField[]>([]);
  readonly targetProps = signal<TargetProperty[]>([]);
  readonly links = signal<{ source: string; target: string; targetKind: 'instance_uri' | 'property'; targetPropertyId?: string | null }[]>([]);
  readonly mappings = signal<MappingRead[]>([]);
  readonly selectedMappingIds = signal<Set<string>>(new Set());
  readonly ontologyModels = signal<OntologyModelRead[]>([]);

  ngOnDestroy(): void {
    this.stopPolling();
  }

  bootstrap(): void {
    this.schemasApi.list({ page: 1, page_size: 100 }).subscribe({
      next: (r) => {
        const published = r.items.filter((s) => s.status === 'published');
        const rest = r.items.filter((s) => s.status !== 'published');
        const ordered = [...published, ...rest];
        this.schemas.set(ordered);
        if (ordered[0]) this.setSchema(ordered[0].id);
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
    this.loadOntologyModels();
  }

  currentSchema(): SchemaRead | undefined {
    return this.schemas().find((s) => s.id === this.schemaId());
  }

  /** Jump to any wizard step for independent viewing (soft guards). */
  goToStep(n: number): void {
    if (n < 1 || n > 4) return;
    if (n === this.step()) return;

    if (n >= 2 && !this.schemaId()) {
      this.toast.error('请先选择目标 Schema');
      return;
    }
    if (n === 4) {
      const mode = this.mode();
      if (mode === 'models') return;
      this.previewView.set(mode);
      this.previewClassId.set(null);
      const bucket = mode === 'struct' ? this.structPreview() : this.unstructPreview();
      if (!bucket.instances.length) {
        this.loadModePreview(mode, false);
      }
    }

    this.step.set(n);
    if (n > this.maxReachedStep()) this.maxReachedStep.set(n);
    if (n === 3) {
      const t = this.task();
      if (t && !t.id) return;
      if (t && (t.status === 'pending' || t.status === 'running')) return;
      this.resumeActiveTask(this.schemaId());
    }
  }

  canViewStep(n: number): boolean {
    if (n <= 1) return true;
    return !!this.schemaId();
  }

  setMode(mode: 'unstruct' | 'struct' | 'models'): void {
    this.mode.set(mode);
    if (mode === 'models') {
      this.loadOntologyModels();
      return;
    }
    this.previewView.set(mode);
    this.previewClassId.set(null);
    this.goToStep(1);
  }

  setSchema(id: string): void {
    this.schemaId.set(id);
    const schema = this.schemas().find((s) => s.id === id);
    this.inventoryVersion.set(schema?.version ?? null);
    this.selectedMappingIds.set(new Set());
    this.unstructPreview.set(emptyPreview());
    this.structPreview.set(emptyPreview());
    this.mergedPreview.set(emptyPreview());
    this.previewView.set(this.mode() === 'struct' ? 'struct' : 'unstruct');
    this.previewClassId.set(null);
    this.task.set(null);
    this.schemasApi.classes(id).subscribe({ next: (c) => this.classes.set(c) });
    this.reloadMappings();
    this.refreshInventory();
  }

  /** Refresh saved mappings and drop stale checkbox selections. */
  reloadMappings(): void {
    const id = this.schemaId();
    if (!id) {
      this.mappings.set([]);
      this.selectedMappingIds.set(new Set());
      return;
    }
    this.mappingsApi.list({ schema_id: id }).subscribe({
      next: (m) => {
        this.mappings.set(m);
        const valid = new Set(m.map((x) => x.id));
        const selected = new Set([...this.selectedMappingIds()].filter((x) => valid.has(x)));
        this.selectedMappingIds.set(selected);
      },
      error: () => {
        this.mappings.set([]);
        this.selectedMappingIds.set(new Set());
      },
    });
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

  /** Export Schema TBox + current-version ABox as Turtle. */
  exportTtl(includeInstances = true): void {
    const id = this.schemaId();
    const schema = this.currentSchema();
    if (!id || !schema) return;
    const ver =
      this.inventoryVersion() ??
      (this.task()?.output_summary?.['schema_version'] as number | undefined) ??
      schema.version;
    this.schemasApi
      .exportTtl(id, { include_instances: includeInstances, schema_version: ver })
      .subscribe({
        next: (ttl) => {
          const blob = new Blob([ttl], { type: 'text/turtle' });
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          const suffix = includeInstances ? `_v${ver}_populated` : `_v${ver}`;
          a.download = `${schema.name}${suffix}.ttl`;
          a.click();
          URL.revokeObjectURL(a.href);
          this.toast.success(includeInstances ? 'Schema + 实例 TTL 已导出' : 'Schema TTL 已导出');
        },
        error: () => this.toast.error('TTL 导出失败'),
      });
  }

  browseInventory(): void {
    this.showMergedPreview();
  }

  /** Combined preview of unstructured + structured instances for the selected schema version. */
  showMergedPreview(): void {
    const id = this.schemaId();
    if (!id) return;
    const ver = this.inventoryVersion();
    this.previewClassId.set(null);
    this.previewView.set('merged');
    this.schemasApi.instanceInventory(id, ver).subscribe({
      next: (inv) => this.inventory.set(inv),
    });
    this.schemasApi.listInstances(id, {
      schema_version: ver,
      page: 1,
      page_size: 200,
    }).subscribe({
      next: (r) => {
        const items = r.items ?? [];
        this.inventoryInstances.set(items);
        this.inventoryTotal.set(r.total ?? 0);
        this.mergedPreview.set({
          task: null,
          instances: items,
          stats: statsFromInstances(items),
        });
        this.step.set(4);
        if (4 > this.maxReachedStep()) this.maxReachedStep.set(4);
        this.toast.success(`合并预览：共 ${r.total ?? items.length} 条实例`);
      },
      error: () => this.toast.error('加载合并预览失败'),
    });
  }

  /** Reload preview for one submodule from instance library (filtered by source_type). */
  showModePreview(): void {
    const mode = this.mode() === 'struct' ? 'struct' : 'unstruct';
    this.loadModePreview(mode, true);
  }

  private loadModePreview(mode: 'unstruct' | 'struct', enterStep4: boolean): void {
    const id = this.schemaId();
    if (!id) return;
    const sourceType = mode === 'struct' ? 'structured_mapping' : 'ai_unstructured';
    const ver = this.inventoryVersion();
    this.previewView.set(mode);
    this.previewClassId.set(null);
    this.schemasApi.listInstances(id, {
      schema_version: ver,
      source_type: sourceType,
      page: 1,
      page_size: 200,
    }).subscribe({
      next: (r) => {
        const items = r.items ?? [];
        const bucket: PreviewBucket = {
          task: mode === 'struct' ? this.structPreview().task : this.unstructPreview().task,
          instances: items,
          stats: statsFromInstances(items),
        };
        if (mode === 'struct') this.structPreview.set(bucket);
        else this.unstructPreview.set(bucket);
        if (enterStep4) {
          this.step.set(4);
          if (4 > this.maxReachedStep()) this.maxReachedStep.set(4);
        }
      },
      error: () => {
        if (enterStep4) this.toast.error('加载子模块预览失败');
      },
    });
  }

  private writeModePreview(
    mode: 'unstruct' | 'struct',
    task: ExtractionTaskRead | null,
    items: InstanceRead[],
  ): void {
    const bucket: PreviewBucket = {
      task,
      instances: items,
      stats: statsFromInstances(items),
    };
    if (mode === 'struct') this.structPreview.set(bucket);
    else this.unstructPreview.set(bucket);
    this.previewView.set(mode);
    this.previewClassId.set(null);
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
    this.selectedDbSourceId.set(sourceId || '');
    this.tables.set([]);
    this.selectedTableId.set('');
    if (!sourceId) return;
    this.tablesLoading.set(true);
    this.dbApi.tables(sourceId).subscribe({
      next: (rows) => {
        const all = rows ?? [];
        const marked = all.filter((x) => x.selected_for_modeling);
        // Prefer tables marked for modeling; if none marked yet, show all reflected tables
        // so structured extraction can proceed without a prior trip to 结构化数据管理.
        this.tables.set(marked.length ? marked : all);
        this.tablesLoading.set(false);
        // Re-sync may recreate tables; refresh mappings so UI never keeps deleted IDs.
        this.reloadMappings();
        if (!all.length) {
          this.toast.error('该数据源下未反射到任何表，请检查连接权限或库中是否有表');
        } else if (!marked.length) {
          this.toast.success(`已加载 ${all.length} 张表（尚未勾选建模表，已全部列出）`);
        }
      },
      error: () => {
        this.tablesLoading.set(false);
        this.tables.set([]);
        this.toast.error('加载表清单失败，请确认数据源可连接');
      },
    });
  }

  openMapping(tableId: string, classId: string): void {
    this.selectedTableId.set(tableId);
    this.selectedClassId.set(classId);
    this.mappingsApi.sourceFields(tableId).subscribe({ next: (f) => this.sourceFields.set(f) });
    this.mappingsApi.targetProperties(classId).subscribe({ next: (p) => this.targetProps.set(p) });
    this.links.set([]);
  }

  addLink(sourceCol: string, target: TargetProperty): void {
    const isUri = target.target_kind === 'instance_uri' || target.kind === 'instance_uri';
    const next = this.links().filter(
      (l) => l.source !== sourceCol && !(isUri && l.targetKind === 'instance_uri'),
    );
    next.push({
      source: sourceCol,
      target: target.id || '__uri__',
      targetKind: isUri ? 'instance_uri' : 'property',
      targetPropertyId: isUri ? null : target.id,
    });
    this.links.set(next);
  }

  saveMapping(onDone?: () => void): void {
    if (!this.links().some((l) => l.targetKind === 'instance_uri')) {
      this.toast.error('请至少绑定一个字段作为实例 URI');
      return;
    }
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
      next: (saved) => {
        this.toast.success('映射已保存');
        this.mappingsApi.list({ schema_id: this.schemaId() }).subscribe({
          next: (m) => {
            this.mappings.set(m);
            const valid = new Set(m.map((x) => x.id));
            const selected = new Set([...this.selectedMappingIds()].filter((x) => valid.has(x)));
            selected.add(saved.id);
            this.selectedMappingIds.set(selected);
          },
        });
        onDone?.();
      },
    });
  }

  deleteMapping(id: string): void {
    this.mappingsApi.remove(id).subscribe({
      next: () => {
        this.mappings.set(this.mappings().filter((m) => m.id !== id));
        const selected = new Set(this.selectedMappingIds());
        selected.delete(id);
        this.selectedMappingIds.set(selected);
        this.toast.success('映射已删除');
      },
      error: () => this.toast.error('删除映射失败'),
    });
  }

  startUnstructured(): void {
    if (!this.selectedModelId()) {
      this.toast.error('请选择用于抽取的模型');
      return;
    }
    this.unstructPreview.set(emptyPreview());
    this.previewView.set('unstruct');
    this.previewClassId.set(null);
    this.beginFreshTask('instance_unstructured');
    this.extraction.startUnstructured({
      schema_id: this.schemaId(),
      file_ids: [...this.selectedFileIds()],
      model_id: this.selectedModelId(),
      replace_existing: this.replaceExisting(),
    }).subscribe({
      next: (t) => this.poll(t.task_id, 'unstruct'),
      error: () => this.task.set(null),
    });
  }

  startStructured(): void {
    this.structPreview.set(emptyPreview());
    this.previewView.set('struct');
    this.previewClassId.set(null);
    this.beginFreshTask('instance_structured');
    this.extraction.startStructured({
      schema_id: this.schemaId(),
      mapping_ids: [...this.selectedMappingIds()],
    }).subscribe({
      next: (t) => this.poll(t.task_id, 'struct'),
      error: () => this.task.set(null),
    });
  }

  cancelTask(): void {
    const t = this.task();
    if (!t?.id || (t.status !== 'pending' && t.status !== 'running') || this.cancelling()) return;
    this.cancelling.set(true);
    this.extraction.cancelTask(t.id).subscribe({
      next: (updated) => {
        this.stopPolling();
        this.applyTask(updated);
        this.cancelling.set(false);
      },
      error: () => {
        this.cancelling.set(false);
        this.toast.error('终止抽取失败');
      },
    });
  }

  private pollSub?: Subscription;
  private pollingTaskId: string | null = null;
  private taskEpoch = 0;

  private applyTask(t: ExtractionTaskRead): void {
    this.zone.run(() => this.task.set({ ...t, output_summary: t.output_summary ? { ...t.output_summary } : null }));
  }

  private beginFreshTask(taskType: ExtractionTaskRead['task_type']): void {
    this.taskEpoch += 1;
    this.stopPolling();
    this.cancelling.set(false);
    this.applyTask({
      id: '',
      task_type: taskType,
      status: 'pending',
      progress: 0,
      output_summary: { stage: '正在启动抽取…' },
    });
    this.goToStep(3);
  }

  private stopPolling(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = undefined;
    this.pollingTaskId = null;
  }

  private resumeActiveTask(schemaId: string): void {
    const mode = this.mode();
    if (mode === 'models' || !schemaId) return;
    const taskType = mode === 'struct' ? 'instance_structured' : 'instance_unstructured';
    const epoch = this.taskEpoch;
    this.extraction.listTasks({ task_type: taskType, status: 'running', limit: 10 }, { silent: true }).subscribe({
      next: (rows) => {
        if (epoch !== this.taskEpoch) return;
        const hit = rows.find((t) => t.schema_id === schemaId);
        if (!hit) return;
        const current = this.task();
        if (current?.id === hit.id && (current.status === 'pending' || current.status === 'running')) {
          return;
        }
        this.poll(hit.id, mode);
      },
    });
  }

  private poll(taskId: string, mode: 'unstruct' | 'struct'): void {
    this.stopPolling();
    this.pollingTaskId = taskId;
    this.goToStep(3);
    this.pollSub = timer(0, 1000).pipe(
      switchMap(() =>
        this.extraction.getTask(taskId, { silent: true }).pipe(catchError(() => of(null))),
      ),
      filter((t): t is ExtractionTaskRead => !!t),
    ).subscribe({
      next: (t) => {
        if (this.pollingTaskId !== taskId) return;
        this.applyTask(t);
        if (t.status === 'pending' || t.status === 'running') return;
        this.stopPolling();
        if (t.status === 'succeeded') {
          this.pollingTaskId = null;
          const summary = t.output_summary as { succeeded?: number; failed?: number; schema_version?: number } | null;
          const ok = summary?.succeeded ?? 0;
          const fail = summary?.failed ?? 0;
          if (summary?.schema_version != null) this.inventoryVersion.set(summary.schema_version);
          this.extraction.taskInstances(taskId, { page: 1, page_size: 200 }).subscribe({
            next: (r) => {
              const items = r.items ?? [];
              this.writeModePreview(mode, t, items);
              this.step.set(4);
              if (4 > this.maxReachedStep()) this.maxReachedStep.set(4);
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
          this.pollingTaskId = null;
          this.cancelling.set(false);
          if (t.error_message === '用户已终止抽取') this.toast.info('已终止抽取');
          else this.toast.error(t.error_message || '抽取失败');
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

  loadOntologyModels(): void {
    this.ontoApi.list({ page: 1, page_size: 100 }).subscribe({
      next: (r) => this.ontologyModels.set(r.items),
    });
  }

  createOntologyModel(body: OntologyModelCreate, onDone?: () => void): void {
    this.ontoApi.create(body).subscribe({
      next: () => {
        this.toast.success('本体模型已保存');
        this.loadOntologyModels();
        onDone?.();
      },
    });
  }

  updateOntologyModel(id: string, body: OntologyModelUpdate, onDone?: () => void): void {
    this.ontoApi.update(id, body).subscribe({
      next: () => {
        this.toast.success('本体模型已更新');
        this.loadOntologyModels();
        onDone?.();
      },
    });
  }

  deleteOntologyModel(id: string): void {
    this.ontoApi.remove(id).subscribe({
      next: () => {
        this.toast.success('本体模型已删除');
        this.loadOntologyModels();
      },
    });
  }

  useModelForExtraction(model: OntologyModelRead): void {
    this.setSchema(model.schema_id);
    this.setInventoryVersion(model.schema_version);
    this.setMode('unstruct');
    this.goToStep(2);
    this.toast.info(`已切换到「${model.name}」对应的 Schema v${model.schema_version}`);
  }
}
