import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { InstanceExtractionStore } from './instance-extraction.store';
import { SegGroupComponent } from '../../../shared/ui/seg-group/seg-group.component';
import { ProgressBarComponent } from '../../../shared/ui/progress-bar/progress-bar.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { ModalComponent } from '../../../shared/ui/modal/modal.component';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { TargetProperty, MappingRead } from '../../../core/models/mapping';
import { OntologyModelRead } from '../../../core/models/ontology-model';
import { SchemasApi } from '../../../core/api/schemas.api';
import { ConfirmDialogService } from '../../../core/services/confirm-dialog.service';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'app-instance-extraction-page',
  standalone: true,
  imports: [
    FormsModule, RouterLink, DatePipe, DecimalPipe, SegGroupComponent, ProgressBarComponent,
    BadgeComponent, ModalComponent, EmptyStateComponent, LucideDynamicIcon,
  ],
  providers: [InstanceExtractionStore],
  templateUrl: './instance-extraction.page.html',
  styleUrl: './instance-extraction.page.scss',
})
export class InstanceExtractionPage implements OnInit {
  readonly store = inject(InstanceExtractionStore);
  private readonly schemasApi = inject(SchemasApi);
  private readonly confirm = inject(ConfirmDialogService);
  readonly mappingOpen = signal(false);
  readonly detailOpen = signal(false);
  readonly modelModalOpen = signal(false);
  readonly editingModel = signal<OntologyModelRead | null>(null);
  readonly dragSource = signal<string | null>(null);
  mapTableId = '';
  mapClassId = '';
  draftName = '';
  draftDesc = '';
  draftSchemaId = '';
  draftVersion: number | null = null;
  draftVersions: number[] = [];
  draftInstanceCount = 0;

  ngOnInit(): void { this.store.bootstrap(); }

  onDbSourceChange(sourceId: string): void {
    this.mapTableId = '';
    this.store.loadTables(sourceId);
  }

  openMapping(): void {
    if (!this.mapTableId || !this.mapClassId) return;
    this.store.openMapping(this.mapTableId, this.mapClassId);
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

  mappingLabel(m: MappingRead): string {
    const cls = this.store.classes().find((c) => c.id === m.class_id)?.label
      ?? m.class_id.slice(0, 8);
    const table = this.store.tables().find((t) => t.id === m.table_id);
    const tableName = table ? `${table.table_schema}.${table.table_name}` : m.table_id.slice(0, 8);
    const uriCol = m.bindings?.find((b) => b.target_kind === 'instance_uri')?.source_column;
    const uriHint = uriCol ? ` · URI=${uriCol}` : ' · 缺实例URI';
    return `${cls} ← ${tableName}${uriHint}`;
  }

  confirmDeleteMapping(id: string, ev: Event): void {
    ev.preventDefault();
    ev.stopPropagation();
    if (!confirm('确认删除该字段映射？此操作不可恢复。')) return;
    this.store.deleteMapping(id);
  }

  sourceTypeLabel(sourceType: string): string {
    if (sourceType === 'ai_unstructured') return '非结构化';
    if (sourceType === 'structured_mapping') return '结构化';
    if (sourceType === 'manual') return '手工';
    return sourceType;
  }

  openCreateModel(): void {
    this.editingModel.set(null);
    this.draftName = '';
    this.draftDesc = '';
    this.draftSchemaId = this.store.schemaId();
    this.draftVersion = this.store.inventoryVersion();
    this.draftVersions = [];
    this.draftInstanceCount = 0;
    this.modelModalOpen.set(true);
    if (this.draftSchemaId) this.onDraftSchemaChange(this.draftSchemaId);
  }

  openSaveAsModel(): void {
    const schema = this.store.currentSchema();
    const ver = this.store.inventoryVersion() ?? schema?.version ?? null;
    this.editingModel.set(null);
    this.draftName = schema ? `${schema.name} · v${ver ?? schema.version}` : '';
    this.draftDesc = '';
    this.draftSchemaId = this.store.schemaId();
    this.draftVersion = ver;
    this.draftInstanceCount = this.store.inventory()?.total ?? 0;
    const versions = this.store.inventory()?.versions ?? [];
    this.draftVersions = versions.length ? versions : (ver != null ? [ver] : []);
    this.modelModalOpen.set(true);
    this.store.setMode('models');
  }

  openEditModel(row: OntologyModelRead): void {
    this.editingModel.set(row);
    this.draftName = row.name;
    this.draftDesc = row.description || '';
    this.draftSchemaId = row.schema_id;
    this.draftVersion = row.schema_version;
    this.modelModalOpen.set(true);
  }

  onDraftSchemaChange(schemaId: string): void {
    this.draftSchemaId = schemaId;
    if (!schemaId) return;
    this.schemasApi.instanceInventory(schemaId).subscribe({
      next: (inv) => {
        const versions = inv.versions.length ? inv.versions : [inv.schema_version];
        this.draftVersions = versions;
        const preferred = this.draftVersion && versions.includes(this.draftVersion)
          ? this.draftVersion
          : inv.filter_version ?? inv.schema_version;
        this.onDraftVersionChange(preferred);
      },
    });
  }

  onDraftVersionChange(version: number): void {
    this.draftVersion = version;
    if (!this.draftSchemaId) return;
    this.schemasApi.instanceInventory(this.draftSchemaId, version).subscribe({
      next: (inv) => { this.draftInstanceCount = inv.total; },
    });
  }

  saveModel(): void {
    const name = this.draftName.trim();
    if (!name) return;
    const editing = this.editingModel();
    if (editing) {
      this.store.updateOntologyModel(editing.id, { name, description: this.draftDesc }, () => this.modelModalOpen.set(false));
      return;
    }
    if (!this.draftSchemaId) return;
    this.store.createOntologyModel({
      name,
      description: this.draftDesc,
      schema_id: this.draftSchemaId,
      schema_version: this.draftVersion,
    }, () => this.modelModalOpen.set(false));
  }

  async removeModel(row: OntologyModelRead): Promise<void> {
    const ok = await this.confirm.confirm({
      title: '删除本体模型',
      message: `确定删除「${row.name}」？不会删除 Schema 或实例，仅去掉这个命名入口。`,
      danger: true,
      confirmText: '删除',
    });
    if (ok) this.store.deleteOntologyModel(row.id);
  }
}
