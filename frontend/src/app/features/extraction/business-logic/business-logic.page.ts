import { Component, OnInit, ViewChild, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { BusinessLogicStore } from './business-logic.store';
import { TopologyCanvasComponent } from './topology-canvas.component';
import { TopologyInspectorComponent } from './topology-inspector.component';
import { ProgressBarComponent } from '../../../shared/ui/progress-bar/progress-bar.component';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { CodeBlockComponent } from '../../../shared/ui/code-block/code-block.component';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'app-business-logic-page',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    TopologyCanvasComponent,
    TopologyInspectorComponent,
    ProgressBarComponent,
    EmptyStateComponent,
    BadgeComponent,
    CodeBlockComponent,
    LucideDynamicIcon,
  ],
  templateUrl: './business-logic.page.html',
  styleUrl: './business-logic.page.scss',
})
export class BusinessLogicPage implements OnInit {
  readonly store = inject(BusinessLogicStore);
  @ViewChild(TopologyCanvasComponent) canvas?: TopologyCanvasComponent;
  showJson = false;
  remountId = '';

  ngOnInit(): void { this.store.bootstrap(); }

  onSelectNode(id: string | null): void {
    this.store.selectNode(id);
    const node = this.store.selectedNode();
    const oid = String(node?.properties?.['selectedObjectId'] ?? '');
    this.remountId = !oid || oid === '自定义' ? '' : oid;
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

  openFullscreen(): void {
    this.showJson = false;
    requestAnimationFrame(() => this.canvas?.setFullscreen(true));
  }

  warningVariant(level?: string): string {
    if (level === 'error') return 'b-danger';
    if (level === 'warning') return 'b-warning';
    return 'b-neutral';
  }
}
