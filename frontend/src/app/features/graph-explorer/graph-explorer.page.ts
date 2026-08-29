import { Component, OnInit, ViewChild, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { GraphExplorerStore } from './graph-explorer.store';
import { D3ForceGraphComponent } from './d3-force-graph.component';
import { SegGroupComponent } from '../../shared/ui/seg-group/seg-group.component';
import { SearchBoxComponent } from '../../shared/ui/search-box/search-box.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state/empty-state.component';
import { LucideDynamicIcon } from '@lucide/angular';
import { GraphMode } from '../../core/models/graph';
import { ToastService } from '../../core/services/toast.service';

@Component({
  selector: 'app-graph-explorer-page',
  standalone: true,
  imports: [FormsModule, D3ForceGraphComponent, SegGroupComponent, SearchBoxComponent, EmptyStateComponent, LucideDynamicIcon],
  providers: [GraphExplorerStore],
  templateUrl: './graph-explorer.page.html',
  styleUrl: './graph-explorer.page.scss',
})
export class GraphExplorerPage implements OnInit {
  readonly store = inject(GraphExplorerStore);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastService);
  @ViewChild(D3ForceGraphComponent) graph?: D3ForceGraphComponent;

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    this.store.bootstrap({
      schemaId: q.get('schema_id') || undefined,
      nodeId: q.get('node') || undefined,
    });
  }

  onMode(v: string): void { this.store.setMode(v as GraphMode); }

  async copyNodeId(): Promise<void> {
    const id = this.store.detail()?.id;
    if (!id) return;
    try {
      await navigator.clipboard.writeText(id);
      this.toast.success('已复制节点 ID');
    } catch {
      this.toast.error('复制失败');
    }
  }
}
