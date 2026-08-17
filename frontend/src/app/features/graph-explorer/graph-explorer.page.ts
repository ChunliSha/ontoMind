import { Component, OnInit, ViewChild, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { GraphExplorerStore } from './graph-explorer.store';
import { D3ForceGraphComponent } from './d3-force-graph.component';
import { SegGroupComponent } from '../../shared/ui/seg-group/seg-group.component';
import { SearchBoxComponent } from '../../shared/ui/search-box/search-box.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state/empty-state.component';
import { LucideDynamicIcon } from '@lucide/angular';
import { GraphMode } from '../../core/models/graph';

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
  @ViewChild(D3ForceGraphComponent) graph?: D3ForceGraphComponent;

  ngOnInit(): void { this.store.bootstrap(); }

  onMode(v: string): void { this.store.setMode(v as GraphMode); }
}
