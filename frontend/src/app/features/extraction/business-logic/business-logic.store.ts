import { Injectable, computed, inject, signal } from '@angular/core';
import { ExtractionApi } from '../../../core/api/extraction.api';
import { TopologyApi } from '../../../core/api/topology.api';
import { FilesApi } from '../../../core/api/files.api';
import { LlmModelsApi } from '../../../core/api/llm-models.api';
import { OntologyModelsApi } from '../../../core/api/ontology-models.api';
import { FileRead } from '../../../core/models/file';
import { LlmModelRead } from '../../../core/models/llm';
import { OntologyModelRead } from '../../../core/models/ontology-model';
import { ExtractionTaskRead } from '../../../core/models/extraction';
import {
  CatalogInstance,
  InstanceCatalogResponse,
  TopologyNode,
  TopologyRead,
  TopologySummary,
  TopologyWarning,
} from '../../../core/models/topology';
import { ToastService } from '../../../core/services/toast.service';
import { Subscription, catchError, filter, of, switchMap, takeWhile, timer } from 'rxjs';

export interface ClassLegendItem {
  type: string;
  color: string;
  count: number;
  custom: boolean;
}

interface SavedTask {
  taskId: string;
  ontoModelId: string;
}

const TASK_KEY = 'ontomind.bizlogic.task';

@Injectable({ providedIn: 'root' })
export class BusinessLogicStore {
  private readonly extraction = inject(ExtractionApi);
  private readonly topologyApi = inject(TopologyApi);
  private readonly filesApi = inject(FilesApi);
  private readonly llmApi = inject(LlmModelsApi);
  private readonly ontoApi = inject(OntologyModelsApi);
  private readonly toast = inject(ToastService);
  private pollSub?: Subscription;
  private bootstrapped = false;

  readonly ontoModels = signal<OntologyModelRead[]>([]);
  readonly ontoModelId = signal('');
  readonly files = signal<FileRead[]>([]);
  readonly selectedFileIds = signal<Set<string>>(new Set());
  readonly models = signal<LlmModelRead[]>([]);
  readonly selectedModelId = signal<string | null>(null);

  readonly catalog = signal<InstanceCatalogResponse | null>(null);
  readonly topologies = signal<TopologySummary[]>([]);

  readonly task = signal<ExtractionTaskRead | null>(null);
  readonly extracting = signal(false);
  readonly topology = signal<TopologyRead | null>(null);
  readonly selectedNodeId = signal<string | null>(null);
  readonly saving = signal(false);

  readonly currentOntoModel = computed(() => this.ontoModels().find((m) => m.id === this.ontoModelId()) ?? null);
  readonly schemaId = computed(() => this.currentOntoModel()?.schema_id ?? '');
  readonly schemaVersion = computed(() => this.currentOntoModel()?.schema_version ?? null);
  readonly warnings = computed<TopologyWarning[]>(() => this.topology()?.warnings ?? []);
  readonly selectedNode = computed(() => {
    const id = this.selectedNodeId();
    const graph = this.topology()?.graph;
    if (!id || !graph) return null;
    return graph.nodes.find((n) => n.id === id) ?? null;
  });
  readonly groundedRatio = computed(() => this.topology()?.grounded_ratio ?? 0);
  readonly ungroundedCount = computed(() =>
    (this.topology()?.graph.nodes ?? []).filter((n) => this.nodeUngrounded(n)).length,
  );
  readonly classLegend = computed<ClassLegendItem[]>(() => {
    const nodes = this.topology()?.graph.nodes ?? [];
    const map = new Map<string, ClassLegendItem>();
    for (const n of nodes) {
      const custom = this.nodeUngrounded(n);
      const key = custom ? '__custom__' : n.type;
      const cur = map.get(key);
      if (cur) cur.count += 1;
      else {
        map.set(key, {
          type: custom ? '自定义（未挂载）' : n.type,
          color: custom ? '#FFE082' : (n.color || '#E5E7EB'),
          count: 1,
          custom,
        });
      }
    }
    return [...map.values()].sort((a, b) => Number(b.custom) - Number(a.custom) || b.count - a.count);
  });
  readonly progressLabel = computed(() => {
    const p = this.task()?.progress ?? 0;
    if (p < 20) return '读取文档';
    if (p < 40) return '理解业务逻辑';
    if (p < 80) return '对齐实例并生成拓扑';
    return '完成收尾';
  });
  readonly canExtract = computed(() =>
    !!this.ontoModelId() && !!this.selectedModelId() && this.selectedFileIds().size > 0 && !this.extracting(),
  );

  bootstrap(): void {
    this.ontoApi.list({ min_instances: 1, page: 1, page_size: 100 }).subscribe({
      next: (r) => {
        this.ontoModels.set(r.items);
        if (this.extracting() || this.ontoModelId()) {
          if (this.ontoModelId()) {
            this.loadCatalog();
            this.loadTopologies();
          }
          return;
        }
        const saved = this.readSavedTask();
        const prefer =
          saved?.ontoModelId && r.items.some((m) => m.id === saved.ontoModelId)
            ? saved.ontoModelId
            : r.items[0]?.id;
        if (prefer) this.setOntoModel(prefer);
      },
    });
    this.filesApi.list({ status: 'ready', page: 1, page_size: 100 }).subscribe({
      next: (r) => this.files.set(r.items),
    });
    this.llmApi.listActive().subscribe({
      next: (rows) => {
        this.models.set(rows);
        const def = rows.find((m) => m.is_default) ?? rows[0];
        if (def && !this.selectedModelId()) this.selectedModelId.set(def.id);
      },
    });
    if (!this.bootstrapped) {
      this.bootstrapped = true;
      this.resumeSavedTask();
    }
  }

  setOntoModel(id: string): void {
    const same = this.ontoModelId() === id;
    this.ontoModelId.set(id);
    if (!same && !this.extracting()) {
      this.topology.set(null);
      this.task.set(null);
      this.selectedNodeId.set(null);
    }
    this.loadCatalog();
    this.loadTopologies();
  }

  loadCatalog(): void {
    const sid = this.schemaId();
    const version = this.schemaVersion();
    if (!sid) return;
    this.topologyApi.instanceCatalog(sid, version).subscribe({
      next: (res) => this.catalog.set(res),
    });
  }

  loadTopologies(): void {
    const mid = this.ontoModelId();
    if (!mid) return;
    this.topologyApi.list(undefined, undefined, mid).subscribe({
      next: (rows) => this.topologies.set(rows),
    });
  }

  remountCandidates(): CatalogInstance[] {
    const all = this.catalog()?.instances ?? [];
    const node = this.selectedNode();
    if (!node || !all.length) return all;
    const same = all.filter((i) => i.class_label === node.type);
    const rest = all.filter((i) => i.class_label !== node.type);
    return [...same, ...rest];
  }

  toggleFile(id: string): void {
    const next = new Set(this.selectedFileIds());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.selectedFileIds.set(next);
  }

  start(): void {
    if (!this.ontoModelId()) {
      this.toast.error('请选择本体模型');
      return;
    }
    if (!this.selectedModelId()) {
      this.toast.error('请选择用于抽取的模型');
      return;
    }
    if (!this.selectedFileIds().size) {
      this.toast.error('请选择至少一份已解析文档');
      return;
    }
    this.extracting.set(true);
    this.topology.set(null);
    this.selectedNodeId.set(null);
    this.extraction.startBusinessLogic({
      ontology_model_id: this.ontoModelId(),
      schema_id: this.schemaId() || null,
      file_ids: [...this.selectedFileIds()],
      model_id: this.selectedModelId(),
      schema_version: this.schemaVersion(),
    }).subscribe({
      next: (t) => this.poll(t.task_id),
      error: () => this.extracting.set(false),
    });
  }

  private poll(taskId: string): void {
    this.pollSub?.unsubscribe();
    this.saveTask(taskId);
    this.pollSub = timer(0, 2000).pipe(
      switchMap(() =>
        this.extraction.getTask(taskId, { silent: true }).pipe(
          catchError(() => of(null as ExtractionTaskRead | null)),
        ),
      ),
      filter((x): x is ExtractionTaskRead => x != null),
      takeWhile((x) => x.status === 'pending' || x.status === 'running', true),
    ).subscribe({
      next: (task) => {
        this.task.set(task);
        if (task.status === 'succeeded') {
          this.extracting.set(false);
          this.clearSavedTask();
          this.loadResult(taskId);
        } else if (task.status === 'failed') {
          this.extracting.set(false);
          this.clearSavedTask();
          this.toast.error(task.error_message || '抽取失败');
        }
      },
    });
  }

  private loadResult(taskId: string): void {
    this.topologyApi.byTask(taskId).subscribe({
      next: (topo) => {
        this.topology.set(topo);
        this.loadTopologies();
        this.toast.success('业务逻辑拓扑抽取完成');
      },
    });
  }

  private resumeSavedTask(): void {
    if (this.extracting()) return;
    const saved = this.readSavedTask();
    this.extraction.listTasks(
      { task_type: 'business_logic_topology', status: 'running', limit: 5 },
      { silent: true },
    ).subscribe({
      next: (rows) => {
        const running = saved
          ? rows.find((t) => t.id === saved.taskId) ?? rows[0]
          : rows[0];
        if (running) {
          if (saved?.ontoModelId && !this.ontoModelId()) {
            this.ontoModelId.set(saved.ontoModelId);
          }
          this.extracting.set(true);
          this.task.set(running);
          this.poll(running.id);
          return;
        }
        if (!saved) return;
        this.extraction.getTask(saved.taskId, { silent: true }).subscribe({
          next: (t) => {
            this.task.set(t);
            if (saved.ontoModelId && !this.ontoModelId()) {
              this.ontoModelId.set(saved.ontoModelId);
            }
            if (t.status === 'succeeded') this.loadResult(saved.taskId);
            else if (t.status === 'failed') {
              this.toast.error(t.error_message || '抽取失败');
            }
            this.clearSavedTask();
          },
          error: () => this.clearSavedTask(),
        });
      },
    });
  }

  private saveTask(taskId: string): void {
    const payload: SavedTask = { taskId, ontoModelId: this.ontoModelId() };
    sessionStorage.setItem(TASK_KEY, JSON.stringify(payload));
  }

  private clearSavedTask(): void {
    sessionStorage.removeItem(TASK_KEY);
  }

  private readSavedTask(): SavedTask | null {
    try {
      const raw = sessionStorage.getItem(TASK_KEY);
      if (!raw) return null;
      const v = JSON.parse(raw) as SavedTask;
      return v?.taskId ? v : null;
    } catch {
      return null;
    }
  }

  openTopology(id: string): void {
    this.topologyApi.get(id).subscribe({
      next: (topo) => {
        this.topology.set(topo);
        this.selectedNodeId.set(null);
      },
    });
  }

  selectNode(id: string | null): void {
    this.selectedNodeId.set(id);
  }

  remount(nodeId: string, instanceId: string | null): void {
    const topo = this.topology();
    if (!topo) return;
    this.saving.set(true);
    this.topologyApi.patch(topo.id, { remount: { node_id: nodeId, instance_id: instanceId } }).subscribe({
      next: (next) => {
        this.topology.set(next);
        this.saving.set(false);
        this.toast.success(instanceId ? '已挂载到实例' : '已改为自定义节点');
      },
      error: () => this.saving.set(false),
    });
  }

  updateNodeLabel(nodeId: string, label: string): void {
    const topo = this.topology();
    if (!topo) return;
    this.topologyApi.patch(topo.id, { update_node: { id: nodeId, label } }).subscribe({
      next: (next) => this.topology.set(next),
    });
  }

  updateNodeProperty(nodeId: string, key: string, value: string): void {
    const topo = this.topology();
    const node = topo?.graph.nodes.find((n) => n.id === nodeId);
    if (!topo || !node) return;
    this.topologyApi.patch(topo.id, {
      update_node: { id: nodeId, properties: { ...node.properties, [key]: value } },
    }).subscribe({
      next: (next) => this.topology.set(next),
    });
  }

  moveNode(nodeId: string, x: number, y: number): void {
    const topo = this.topology();
    if (!topo) return;
    this.topologyApi.patch(topo.id, { update_node: { id: nodeId, x, y } }).subscribe({
      next: (next) => this.topology.set(next),
    });
  }

  addEdge(sourceId: string, targetId: string, label: string): void {
    const topo = this.topology();
    if (!topo) return;
    this.topologyApi.patch(topo.id, { add_edge: { source_id: sourceId, target_id: targetId, label } }).subscribe({
      next: (next) => this.topology.set(next),
    });
  }

  deleteEdge(edgeId: string): void {
    const topo = this.topology();
    if (!topo) return;
    this.topologyApi.patch(topo.id, { delete_edge_ids: [edgeId] }).subscribe({
      next: (next) => this.topology.set(next),
    });
  }

  export(): void {
    const topo = this.topology();
    if (!topo) return;
    const blob = new Blob([JSON.stringify(topo.graph ?? {}, null, 2)], {
      type: 'application/json;charset=utf-8',
    });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${topo.name || 'business-logic-topology'}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    this.toast.success('已导出 JSON');
  }

  jsonPreview(): string {
    const graph = this.topology()?.graph;
    return graph ? JSON.stringify(graph, null, 2) : '';
  }

  nodeUngrounded(node?: TopologyNode | null): boolean {
    const id = String(node?.properties?.['selectedObjectId'] ?? '');
    return !id || id === '自定义';
  }

  isUngrounded(nodeId?: string | null): boolean {
    const node = nodeId
      ? this.topology()?.graph.nodes.find((n) => n.id === nodeId)
      : this.selectedNode();
    return this.nodeUngrounded(node);
  }
}
