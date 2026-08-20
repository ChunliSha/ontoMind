import { Injectable, computed, inject, signal } from '@angular/core';
import { TopologyApi } from '../../../core/api/topology.api';
import { OntologyModelsApi } from '../../../core/api/ontology-models.api';
import { OntologyModelRead } from '../../../core/models/ontology-model';
import {
  CatalogInstance,
  InstanceCatalogResponse,
  TopologyNode,
  TopologyRead,
  TopologySummary,
  TopologyWarning,
} from '../../../core/models/topology';
import { ToastService } from '../../../core/services/toast.service';
import { ConfirmDialogService } from '../../../core/services/confirm-dialog.service';
import { ClassLegendItem } from './business-logic.store';

@Injectable({ providedIn: 'root' })
export class TopologyWorkspaceStore {
  private readonly topologyApi = inject(TopologyApi);
  private readonly ontoApi = inject(OntologyModelsApi);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmDialogService);

  readonly ontoModels = signal<OntologyModelRead[]>([]);
  readonly filterOntoModelId = signal('');
  readonly topologies = signal<TopologySummary[]>([]);
  readonly topology = signal<TopologyRead | null>(null);
  readonly catalog = signal<InstanceCatalogResponse | null>(null);
  readonly selectedNodeId = signal<string | null>(null);
  readonly saving = signal(false);
  readonly loading = signal(false);

  readonly filteredTopologies = computed(() => {
    const mid = this.filterOntoModelId();
    const rows = this.topologies();
    if (!mid) return rows;
    return rows.filter((t) => t.ontology_model_id === mid);
  });

  readonly currentOntoModel = computed(() => {
    const tid = this.topology()?.ontology_model_id;
    if (!tid) return null;
    return this.ontoModels().find((m) => m.id === tid) ?? null;
  });

  readonly warnings = computed<TopologyWarning[]>(() => this.topology()?.warnings ?? []);
  readonly selectedNode = computed(() => {
    const id = this.selectedNodeId();
    const graph = this.topology()?.graph;
    if (!id || !graph) return null;
    return graph.nodes.find((n) => n.id === id) ?? null;
  });
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

  ontoModelName(id?: string | null): string {
    if (!id) return '未关联模型';
    return this.ontoModels().find((m) => m.id === id)?.name ?? '本体模型';
  }

  bootstrap(preferredId?: string | null): void {
    this.ontoApi.list({ page: 1, page_size: 100 }).subscribe({
      next: (r) => this.ontoModels.set(r.items),
    });
    this.refreshList(preferredId);
  }

  refreshList(preferredId?: string | null): void {
    this.loading.set(true);
    this.topologyApi.list().subscribe({
      next: (rows) => {
        this.topologies.set(rows);
        this.loading.set(false);
        const current = this.topology()?.id;
        const pick =
          (preferredId && rows.find((t) => t.id === preferredId)?.id) ||
          (current && rows.find((t) => t.id === current)?.id) ||
          this.filteredTopologies()[0]?.id;
        if (pick && pick !== current) this.open(pick);
        if (!pick) {
          this.topology.set(null);
          this.selectedNodeId.set(null);
        }
      },
      error: () => this.loading.set(false),
    });
  }

  setFilter(id: string): void {
    this.filterOntoModelId.set(id);
    const rows = this.filteredTopologies();
    if (!rows.some((t) => t.id === this.topology()?.id)) {
      if (rows[0]) this.open(rows[0].id);
      else {
        this.topology.set(null);
        this.selectedNodeId.set(null);
      }
    }
  }

  open(id: string): void {
    this.topologyApi.get(id).subscribe({
      next: (topo) => {
        this.topology.set(topo);
        this.selectedNodeId.set(null);
        this.topologyApi.instanceCatalog(topo.schema_id, topo.schema_version).subscribe({
          next: (res) => this.catalog.set(res),
        });
      },
    });
  }

  selectNode(id: string | null): void {
    this.selectedNodeId.set(id);
  }

  remountCandidates(): CatalogInstance[] {
    const all = this.catalog()?.instances ?? [];
    const node = this.selectedNode();
    if (!node || !all.length) return all;
    const same = all.filter((i) => i.class_label === node.type);
    const rest = all.filter((i) => i.class_label !== node.type);
    return [...same, ...rest];
  }

  rename(name: string): void {
    const topo = this.topology();
    const next = name.trim();
    if (!topo || !next || next === topo.name) return;
    this.topologyApi.patch(topo.id, { name: next }).subscribe({
      next: (row) => {
        this.topology.set(row);
        this.topologies.update((list) => list.map((t) => (t.id === row.id ? { ...t, name: row.name } : t)));
        this.toast.success('已更新名称');
      },
    });
  }

  async remove(id: string): Promise<void> {
    const row = this.topologies().find((t) => t.id === id);
    const ok = await this.confirm.confirm({
      title: '删除业务逻辑',
      message: `确定删除「${row?.name || '未命名拓扑'}」？此操作不可恢复。`,
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    this.topologyApi.remove(id).subscribe({
      next: () => {
        this.toast.success('已删除');
        const rest = this.topologies().filter((t) => t.id !== id);
        this.topologies.set(rest);
        if (this.topology()?.id === id) {
          this.topology.set(null);
          this.selectedNodeId.set(null);
          if (rest[0]) this.open(rest[0].id);
        }
      },
    });
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
