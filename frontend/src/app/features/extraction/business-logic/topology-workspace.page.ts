import { Component, OnInit, ViewChild, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TopologyWorkspaceStore } from './topology-workspace.store';
import { TopologyCanvasComponent } from './topology-canvas.component';
import { TopologyInspectorComponent } from './topology-inspector.component';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { LucideDynamicIcon } from '@lucide/angular';
import { CatalogInstance } from '../../../core/models/topology';

@Component({
  selector: 'app-topology-workspace-page',
  standalone: true,
  imports: [
    FormsModule,
    DatePipe,
    RouterLink,
    TopologyCanvasComponent,
    TopologyInspectorComponent,
    EmptyStateComponent,
    BadgeComponent,
    LucideDynamicIcon,
  ],
  templateUrl: './topology-workspace.page.html',
  styleUrl: './topology-workspace.page.scss',
})
export class TopologyWorkspacePage implements OnInit {
  readonly store = inject(TopologyWorkspaceStore);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  @ViewChild(TopologyCanvasComponent) canvas?: TopologyCanvasComponent;
  remountId = '';
  nameDraft = '';

  ngOnInit(): void {
    const id = this.route.snapshot.queryParamMap.get('id');
    this.store.bootstrap(id);
    this.route.queryParamMap.subscribe((q) => {
      const next = q.get('id');
      if (next && next !== this.store.topology()?.id) this.store.open(next);
    });
  }

  open(id: string): void {
    void this.router.navigate([], { queryParams: { id }, queryParamsHandling: 'merge' });
    this.store.open(id);
  }

  onSelectNode(id: string | null): void {
    this.store.selectNode(id);
    const node = this.store.selectedNode();
    const oid = String(node?.properties?.['selectedObjectId'] ?? '');
    this.remountId = !oid || oid === '自定义' ? '' : oid;
  }

  candidatesForSelected(): CatalogInstance[] {
    return this.store.remountCandidates();
  }

  onRemount(): void {
    const node = this.store.selectedNode();
    if (!node) return;
    this.store.remount(node.id, this.remountId || null);
  }

  onLabelBlur(value: string): void {
    const node = this.store.selectedNode();
    if (!node || value.trim() === node.label) return;
    this.store.updateNodeLabel(node.id, value.trim());
  }

  onPropBlur(key: string, value: string): void {
    const node = this.store.selectedNode();
    if (!node) return;
    const v = node.properties?.[key];
    const current = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);
    if (current === value) return;
    this.store.updateNodeProperty(node.id, key, value);
  }

  onNameBlur(): void {
    this.store.rename(this.nameDraft);
  }

  syncName(): void {
    this.nameDraft = this.store.topology()?.name || '';
  }

  warningVariant(level?: string): string {
    if (level === 'error') return 'b-danger';
    if (level === 'warning') return 'b-warning';
    return 'b-neutral';
  }
}
