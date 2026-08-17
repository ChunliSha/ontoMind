import { Injectable, inject, signal } from '@angular/core';
import { GraphApi } from '../../core/api/graph.api';
import { SchemasApi } from '../../core/api/schemas.api';
import { GraphLink, GraphMode, GraphNode, GraphNodeDetail } from '../../core/models/graph';
import { SchemaRead } from '../../core/models/schema';

@Injectable()
export class GraphExplorerStore {
  private readonly graphApi = inject(GraphApi);
  private readonly schemasApi = inject(SchemasApi);

  readonly schemas = signal<SchemaRead[]>([]);
  readonly schemaId = signal('');
  readonly mode = signal<GraphMode>('mixed');
  readonly nodes = signal<GraphNode[]>([]);
  readonly links = signal<GraphLink[]>([]);
  readonly detail = signal<GraphNodeDetail | null>(null);
  readonly loading = signal(false);
  readonly search = signal('');

  bootstrap(): void {
    // TODO(spec-conflict): UCD prototype used a TTL file picker for graph input;
    // product/API contract requires schema_id selector instead of uploading TTL here.
    this.schemasApi.list({ page: 1, page_size: 100 }).subscribe({
      next: (r) => {
        this.schemas.set(r.items);
        if (r.items[0]) {
          this.schemaId.set(r.items[0].id);
          this.reload();
        }
      },
    });
  }

  setSchema(id: string): void {
    this.schemaId.set(id);
    this.reload();
  }

  setMode(mode: GraphMode): void {
    this.mode.set(mode);
    this.reload();
  }

  reload(): void {
    const id = this.schemaId();
    if (!id) return;
    this.loading.set(true);
    this.graphApi.getGraph(id, this.mode()).subscribe({
      next: (g) => {
        this.nodes.set(g.nodes || []);
        this.links.set(g.links || []);
        this.loading.set(false);
      },
      error: () => {
        this.nodes.set([]);
        this.links.set([]);
        this.loading.set(false);
      },
    });
  }

  selectNode(node: GraphNode): void {
    const nodeType = node.type === 'instance' ? 'instance' : 'class';
    this.graphApi.nodeDetail(node.id, nodeType).subscribe({
      next: (d) => this.detail.set(d),
      error: () => {
        const fields: { key: string; value: string }[] = [{ key: 'rdfs:label', value: node.label }];
        if (node.type === 'class') {
          fields.unshift({ key: '类型', value: 'owl:Class' });
          if (node.dp != null) fields.push({ key: '数据属性', value: `${node.dp} 个` });
          if (node.op != null) fields.push({ key: '对象属性', value: `${node.op} 个` });
          if (node.inst != null) fields.push({ key: '实例数量', value: String(node.inst) });
        } else if (node.type === 'obj_prop') {
          fields.unshift({ key: '类型', value: 'owl:ObjectProperty' });
        } else if (node.type === 'data_prop') {
          fields.unshift({ key: '类型', value: 'owl:DatatypeProperty' });
        } else {
          fields.unshift({ key: '类型', value: 'owl:NamedIndividual' });
        }
        this.detail.set({ id: node.id, type: node.type, label: node.label, fields });
      },
    });
  }
}
