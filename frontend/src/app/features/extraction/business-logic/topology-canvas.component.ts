import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  HostBinding,
  HostListener,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  ViewChild,
  computed,
  input,
  signal,
} from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';
import { TopologyEdge, TopologyGraph, TopologyNode } from '../../../core/models/topology';

export type CanvasVariant = 'compact' | 'workspace';
export interface NodeMoveEvent { id: string; x: number; y: number; }
export interface EdgeAddEvent { sourceId: string; targetId: string; label: string; }

@Component({
  selector: 'app-topology-canvas',
  standalone: true,
  imports: [LucideDynamicIcon],
  templateUrl: './topology-canvas.component.html',
  styleUrl: './topology-canvas.component.scss',
})
export class TopologyCanvasComponent implements OnChanges, AfterViewInit, OnDestroy {
  @Input({ required: true }) graph!: TopologyGraph;
  @Input() selectedId: string | null = null;
  readonly variant = input<CanvasVariant>('compact');
  @Output() selectedIdChange = new EventEmitter<string | null>();
  @Output() nodeMoved = new EventEmitter<NodeMoveEvent>();
  @Output() edgeAdded = new EventEmitter<EdgeAddEvent>();
  @Output() edgeDeleted = new EventEmitter<string>();
  @Output() fullscreenChange = new EventEmitter<boolean>();

  @ViewChild('host', { static: true }) hostRef!: ElementRef<HTMLElement>;

  @HostBinding('class.workspace-fill')
  get fillHost(): boolean {
    return this.variant() === 'workspace' || this.fullscreen();
  }

  @HostBinding('class.is-fullscreen')
  get fullscreenHost(): boolean {
    return this.fullscreen();
  }

  readonly fullscreen = signal(false);
  readonly mode = signal<'select' | 'link'>('select');
  readonly edgeLabel = signal<'' | '是' | '否'>('');
  readonly linkFrom = signal<string | null>(null);
  readonly scale = signal(1);
  readonly panX = signal(40);
  readonly panY = signal(48);
  readonly viewportW = signal(960);
  readonly viewportH = signal(560);

  private dragging: { id: string; dx: number; dy: number } | null = null;
  private panning: { x: number; y: number; panX: number; panY: number } | null = null;
  private moved = false;
  private fittedFor = '';
  private ro?: ResizeObserver;
  readonly draftPos = signal<Record<string, { x: number; y: number }>>({});

  readonly nodeW = computed(() => (this.variant() === 'workspace' || this.fullscreen() ? 300 : 240));
  readonly nodeH = computed(() => (this.variant() === 'workspace' || this.fullscreen() ? 132 : 92));

  ngOnChanges(changes: SimpleChanges): void {
    if (!changes['graph']) return;
    const prev = changes['graph'].previousValue as TopologyGraph | undefined;
    this.draftPos.set({});
    if (changes['graph'].firstChange || this.graphIdentity(prev) !== this.graphIdentity(this.graph)) {
      this.fittedFor = '';
      queueMicrotask(() => this.fitView());
    }
  }

  ngAfterViewInit(): void {
    this.ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (!r?.width || !r?.height) return;
      const jumped = Math.abs(r.width - this.viewportW()) > 40 || Math.abs(r.height - this.viewportH()) > 40;
      this.viewportW.set(r.width);
      this.viewportH.set(r.height);
      if (!this.fittedFor || jumped) this.fitView();
    });
    this.ro.observe(this.hostRef.nativeElement);
  }

  toggleFullscreen(): void {
    this.setFullscreen(!this.fullscreen());
  }

  setFullscreen(on: boolean): void {
    this.fullscreen.set(on);
    this.fullscreenChange.emit(on);
    document.body.style.overflow = on ? 'hidden' : '';
    this.fittedFor = '';
    requestAnimationFrame(() => requestAnimationFrame(() => this.fitView()));
  }

  @HostListener('document:keydown.escape')
  onEsc(): void {
    if (this.fullscreen() && this.selectedId) {
      this.selectedIdChange.emit(null);
      return;
    }
    if (this.fullscreen()) {
      this.setFullscreen(false);
      return;
    }
    this.linkFrom.set(null);
    this.mode.set('select');
  }

  ngOnDestroy(): void {
    this.ro?.disconnect();
    if (this.fullscreen()) {
      document.body.style.overflow = '';
      this.fullscreenChange.emit(false);
    }
  }

  readonly bounds = computed(() => {
    const nodes = this.graph?.nodes ?? [];
    const w = this.nodeW();
    const h = this.nodeH();
    if (!nodes.length) return { minX: 0, minY: 0, width: 800, height: 480 };
    const xs = nodes.map((n) => this.nx(n));
    const ys = nodes.map((n) => this.ny(n));
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    const maxX = Math.max(...xs) + w;
    const maxY = Math.max(...ys) + h;
    return { minX, minY, width: Math.max(w, maxX - minX), height: Math.max(h, maxY - minY) };
  });

  nx(node: TopologyNode): number {
    return this.draftPos()[node.id]?.x ?? Number(node.x) ?? 0;
  }

  ny(node: TopologyNode): number {
    return this.draftPos()[node.id]?.y ?? Number(node.y) ?? 0;
  }

  nodeById(id: string): TopologyNode | undefined {
    return this.graph.nodes.find((n) => n.id === id);
  }

  portPoint(node: TopologyNode, port?: string | null): { x: number; y: number } {
    const x = this.nx(node);
    const y = this.ny(node);
    const w = this.nodeW();
    const h = this.nodeH();
    const cx = x + w / 2;
    const cy = y + h / 2;
    switch (port) {
      case 'port-top': return { x: cx, y };
      case 'port-bottom': return { x: cx, y: y + h };
      case 'port-left': return { x, y: cy };
      case 'port-right': return { x: x + w, y: cy };
      default: return { x: cx, y: y + h };
    }
  }

  edgePath(edge: TopologyEdge): string {
    const s = this.nodeById(edge.source.cell);
    const t = this.nodeById(edge.target.cell);
    if (!s || !t) return '';
    const a = this.portPoint(s, edge.source.port);
    const b = this.portPoint(t, edge.target.port);
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    if (Math.abs(b.y - a.y) >= Math.abs(b.x - a.x)) {
      return `M ${a.x} ${a.y} C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`;
    }
    return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
  }

  edgeLabelPos(edge: TopologyEdge): { x: number; y: number } {
    const s = this.nodeById(edge.source.cell);
    const t = this.nodeById(edge.target.cell);
    if (!s || !t) return { x: 0, y: 0 };
    const a = this.portPoint(s, edge.source.port);
    const b = this.portPoint(t, edge.target.port);
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }

  isUngrounded(node: TopologyNode): boolean {
    const id = String(node.properties?.['selectedObjectId'] ?? '');
    return !id || id === '自定义';
  }

  nodeSnippet(node: TopologyNode): string {
    if (this.isUngrounded(node)) return '未落地 · 请在右侧挂载实例';
    const extra = node.properties?.['judgementContent'] ?? node.properties?.['description'];
    if (extra != null && String(extra).trim()) return String(extra);
    return '已挂载实例';
  }

  fitView(): void {
    const host = this.hostRef?.nativeElement;
    if (!host) return;
    const vw = host.clientWidth || this.viewportW();
    const vh = host.clientHeight || this.viewportH();
    if (vw < 40 || vh < 40) return;
    this.viewportW.set(vw);
    this.viewportH.set(vh);
    const b = this.bounds();
    const pad = 48;
    const sx = (vw - pad * 2) / Math.max(b.width, 1);
    const sy = (vh - pad * 2) / Math.max(b.height, 1);
    const cap = this.variant() === 'workspace' || this.fullscreen() ? 1 : 0.92;
    const k = Math.min(Math.max(Math.min(sx, sy), 0.28), cap);
    this.scale.set(k);
    this.panX.set(pad - b.minX * k + (vw - pad * 2 - b.width * k) / 2);
    this.panY.set(pad - b.minY * k + (vh - pad * 2 - b.height * k) / 2);
    this.fittedFor = this.graph?.workflow_id || 'graph';
  }

  onCanvasDown(ev: PointerEvent, host: HTMLElement): void {
    if ((ev.target as HTMLElement).closest('.topo-node, .topo-edge')) return;
    this.panning = { x: ev.clientX, y: ev.clientY, panX: this.panX(), panY: this.panY() };
    host.setPointerCapture(ev.pointerId);
  }

  onNodeDown(ev: PointerEvent, node: TopologyNode, host: HTMLElement): void {
    ev.stopPropagation();
    this.selectedIdChange.emit(node.id);
    if (this.mode() === 'link') {
      const from = this.linkFrom();
      if (!from) {
        this.linkFrom.set(node.id);
        return;
      }
      if (from !== node.id) {
        this.edgeAdded.emit({ sourceId: from, targetId: node.id, label: this.edgeLabel() });
      }
      this.linkFrom.set(null);
      return;
    }
    this.dragging = { id: node.id, dx: ev.clientX, dy: ev.clientY };
    this.moved = false;
    host.setPointerCapture(ev.pointerId);
  }

  onMove(ev: PointerEvent): void {
    if (this.panning) {
      this.panX.set(this.panning.panX + (ev.clientX - this.panning.x));
      this.panY.set(this.panning.panY + (ev.clientY - this.panning.y));
      return;
    }
    if (!this.dragging) return;
    const k = this.scale();
    const dx = (ev.clientX - this.dragging.dx) / k;
    const dy = (ev.clientY - this.dragging.dy) / k;
    if (Math.abs(dx) + Math.abs(dy) > 2) this.moved = true;
    const node = this.nodeById(this.dragging.id);
    if (!node) return;
    this.draftPos.update((m) => ({
      ...m,
      [node.id]: { x: Number(node.x) + dx, y: Number(node.y) + dy },
    }));
  }

  onUp(): void {
    if (this.dragging && this.moved) {
      const pos = this.draftPos()[this.dragging.id];
      if (pos) this.nodeMoved.emit({ id: this.dragging.id, x: Math.round(pos.x), y: Math.round(pos.y) });
    }
    this.dragging = null;
    this.panning = null;
  }

  onWheel(ev: WheelEvent): void {
    ev.preventDefault();
    const host = this.hostRef.nativeElement;
    const rect = host.getBoundingClientRect();
    const cx = ev.clientX - rect.left;
    const cy = ev.clientY - rect.top;
    const prev = this.scale();
    const next = Math.min(2.4, Math.max(0.25, prev * (ev.deltaY > 0 ? 0.9 : 1.1)));
    const gx = (cx - this.panX()) / prev;
    const gy = (cy - this.panY()) / prev;
    this.scale.set(next);
    this.panX.set(cx - gx * next);
    this.panY.set(cy - gy * next);
  }

  onEdgeClick(ev: MouseEvent, edge: TopologyEdge): void {
    ev.stopPropagation();
    if (this.mode() !== 'select') return;
    if (confirm(`删除这条「${edge.label || '连接'}」边？`)) {
      this.edgeDeleted.emit(edge.id);
    }
  }

  setMode(mode: 'select' | 'link'): void {
    this.mode.set(mode);
    this.linkFrom.set(null);
  }

  trackNode(_: number, n: TopologyNode): string { return n.id; }
  trackEdge(_: number, e: TopologyEdge): string { return e.id; }

  private graphIdentity(graph?: TopologyGraph | null): string {
    if (!graph) return '';
    if (graph.workflow_id) return graph.workflow_id;
    return (graph.nodes ?? []).map((n) => n.id).join('\0');
  }
}
