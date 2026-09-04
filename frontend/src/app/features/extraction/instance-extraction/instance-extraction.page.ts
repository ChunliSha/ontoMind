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
import { InstanceDetail } from '../../../core/models/extraction';
import { PropertyRead } from '../../../core/models/schema';
import { SchemasApi } from '../../../core/api/schemas.api';
import { ConfirmDialogService } from '../../../core/services/confirm-dialog.service';
import { ToastService } from '../../../core/services/toast.service';
import { LucideDynamicIcon } from '@lucide/angular';

interface DraftDataRow {
  key: string;
  property_id: string;
  value: string;
}

interface DraftRelRow {
  key: string;
  property_id: string;
  object_instance_id: string;
}

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
  private readonly toast = inject(ToastService);
  readonly mappingOpen = signal(false);
  readonly detailOpen = signal(false);
  readonly savingInstance = signal(false);
  readonly pendingDelete = signal(false);
  readonly draftClassId = signal('');
  readonly draftData = signal<DraftDataRow[]>([]);
  readonly draftRels = signal<DraftRelRow[]>([]);
  readonly incomingRels = signal<InstanceDetail['relations']>([]);
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
    this.pendingDelete.set(false);
    this.savingInstance.set(false);
    this.store.loadInstance(id, (d) => this.hydrateDraft(d));
    this.detailOpen.set(true);
  }

  private hydrateDraft(d: InstanceDetail): void {
    this.draftClassId.set(d.class_id || '');
    this.pendingDelete.set(false);
    this.draftData.set(
      (d.data_values || []).map((v) => ({
        key: crypto.randomUUID(),
        property_id: v.property_id,
        value: v.value,
      })),
    );
    this.draftRels.set(
      (d.relations || [])
        .filter((r) => (r.direction || 'out') === 'out')
        .map((r) => ({
          key: crypto.randomUUID(),
          property_id: r.property_id,
          object_instance_id: r.object_instance_id,
        })),
    );
    this.incomingRels.set((d.relations || []).filter((r) => r.direction === 'in'));
  }

  closeDetail(): void {
    this.detailOpen.set(false);
    this.pendingDelete.set(false);
  }

  dataProperties(): PropertyRead[] {
    return this.store.schemaProperties().filter((p) => p.kind === 'data');
  }

  objectProperties(): PropertyRead[] {
    return this.store.schemaProperties().filter((p) => p.kind === 'object');
  }

  targetInstances() {
    return this.store.editCandidates();
  }

  hasTargetOption(instanceId: string): boolean {
    return this.store.editCandidates().some((t) => t.id === instanceId);
  }

  addDataRow(): void {
    this.draftData.update((rows) => [
      ...rows,
      { key: crypto.randomUUID(), property_id: '', value: '' },
    ]);
  }

  removeDataRow(key: string): void {
    this.draftData.update((rows) => rows.filter((r) => r.key !== key));
  }

  patchDataRow(key: string, patch: Partial<DraftDataRow>): void {
    this.draftData.update((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  addRelRow(): void {
    this.draftRels.update((rows) => [
      ...rows,
      { key: crypto.randomUUID(), property_id: '', object_instance_id: '' },
    ]);
  }

  removeRelRow(key: string): void {
    this.draftRels.update((rows) => rows.filter((r) => r.key !== key));
  }

  patchRelRow(key: string, patch: Partial<DraftRelRow>): void {
    this.draftRels.update((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  confirmInstanceSave(): void {
    const detail = this.store.instanceDetail();
    if (!detail || this.savingInstance()) return;
    if (this.pendingDelete()) {
      this.savingInstance.set(true);
      this.store.deleteInstance(
        detail.id,
        () => {
          this.savingInstance.set(false);
          this.closeDetail();
        },
        () => this.savingInstance.set(false),
      );
      return;
    }
    const dataRows = this.draftData().filter((r) => r.property_id.trim());
    if (dataRows.some((r) => !r.value.trim())) {
      this.toast.error('请填写数据属性的值，或不需要的行请删除');
      return;
    }
    const relRows = this.draftRels().filter((r) => r.property_id.trim() || r.object_instance_id.trim());
    if (relRows.some((r) => !r.property_id.trim() || !r.object_instance_id.trim())) {
      this.toast.error('请为对象属性选择属性与目标实例');
      return;
    }
    this.savingInstance.set(true);
    this.store.saveInstance(
      detail.id,
      {
        class_id: this.draftClassId().trim() || null,
        data_values: dataRows.map((r) => ({ property_id: r.property_id, value: r.value.trim() })),
        relations: relRows.map((r) => ({
          property_id: r.property_id,
          object_instance_id: r.object_instance_id,
        })),
      },
      () => {
        this.savingInstance.set(false);
        this.closeDetail();
      },
      () => this.savingInstance.set(false),
    );
  }

  relationPropertyLabel(r: {
    property_label?: string | null;
    direction?: 'out' | 'in';
  }): string {
    const name = (r.property_label || '').trim() || '对象属性';
    return r.direction === 'in' ? `${name}（入边）` : name;
  }

  relatedInstanceLabel(r: {
    object_instance_label?: string | null;
    object_label?: string | null;
    object_class_label?: string | null;
    object_instance_id?: string;
  }): string {
    const name = (r.object_instance_label || r.object_label || '').trim();
    if (!name) return r.object_instance_id ? r.object_instance_id.slice(0, 8) : '—';
    const cls = (r.object_class_label || '').trim();
    return cls ? `${name}（${cls}）` : name;
  }

  confirmMapping(): void {
    this.store.saveMapping(() => this.mappingOpen.set(false));
  }

  mappingLabel(m: MappingRead): string {
    const cls = this.store.classes().find((c) => c.id === m.class_id)?.label
      ?? m.class_id.slice(0, 8);
    const uriCol = m.bindings?.find((b) => b.target_kind === 'instance_uri')?.source_column;
    const uriHint = uriCol ? ` · URI=${uriCol}` : ' · 缺实例URI';
    return `${cls}${uriHint}`;
  }

  mappingOrigin(m: MappingRead): string {
    const src = m.data_source_name?.trim() || '未知数据源';
    const schema = (m.table_schema || '').trim();
    const table = (m.table_name || '').trim();
    const tableLabel = table ? (schema ? `${schema}.${table}` : table) : m.table_id.slice(0, 8);
    return `数据源 ${src} · 表 ${tableLabel}`;
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
