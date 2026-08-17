import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { InstanceExtractionStore } from './instance-extraction.store';
import { SegGroupComponent } from '../../../shared/ui/seg-group/seg-group.component';
import { ProgressBarComponent } from '../../../shared/ui/progress-bar/progress-bar.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { ModalComponent } from '../../../shared/ui/modal/modal.component';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { TargetProperty } from '../../../core/models/mapping';

@Component({
  selector: 'app-instance-extraction-page',
  standalone: true,
  imports: [FormsModule, RouterLink, DatePipe, SegGroupComponent, ProgressBarComponent, BadgeComponent, ModalComponent, EmptyStateComponent],
  providers: [InstanceExtractionStore],
  templateUrl: './instance-extraction.page.html',
  styleUrl: './instance-extraction.page.scss',
})
export class InstanceExtractionPage implements OnInit {
  readonly store = inject(InstanceExtractionStore);
  readonly mappingOpen = signal(false);
  readonly detailOpen = signal(false);
  readonly dragSource = signal<string | null>(null);
  mapSourceId = '';
  mapClassId = '';

  ngOnInit(): void { this.store.bootstrap(); }

  openMapping(): void {
    if (!this.mapSourceId || !this.mapClassId) return;
    this.store.openMapping(this.mapSourceId, this.mapClassId);
    this.mappingOpen.set(true);
  }

  onDragStart(col: string): void { this.dragSource.set(col); }
  onDropTarget(tp: TargetProperty): void {
    const src = this.dragSource();
    if (!src) return;
    this.store.addLink(src, tp);
    this.dragSource.set(null);
  }

  maxStat(): number {
    const rows = this.store.stats();
    if (!rows.length) return 1;
    return Math.max(1, ...rows.map((s) => s.count));
  }

  inventoryMaxStat(): number {
    const rows = this.store.inventory()?.by_class ?? [];
    if (!rows.length) return 1;
    return Math.max(1, ...rows.map((s) => s.count));
  }

  confirmClear(): void {
    const ver = this.store.inventoryVersion();
    if (!confirm(`确认清空 Schema 版本 v${ver ?? '—'} 下的全部实例？此操作不可恢复。`)) return;
    this.store.clearInventory();
  }

  showDetail(id: string): void {
    this.store.loadInstance(id);
    this.detailOpen.set(true);
  }

  confirmMapping(): void {
    this.store.saveMapping(() => this.mappingOpen.set(false));
  }
}
