import { Component, OnInit, effect, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { SchemaStudioStore } from './schema-studio.store';
import { BadgeComponent } from '../../shared/ui/badge/badge.component';
import { ModalComponent } from '../../shared/ui/modal/modal.component';
import { SegGroupComponent } from '../../shared/ui/seg-group/seg-group.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state/empty-state.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { LucideDynamicIcon } from '@lucide/angular';
import { ConfirmDialogService } from '../../core/services/confirm-dialog.service';
import { FormErrorService } from '../../core/services/form-error.service';
import { PropertyRead, SchemaRead } from '../../core/models/schema';

@Component({
  selector: 'app-schema-studio-page',
  standalone: true,
  imports: [ReactiveFormsModule, FormsModule, BadgeComponent, ModalComponent, SegGroupComponent, EmptyStateComponent, RelativeTimePipe, LucideDynamicIcon],
  providers: [SchemaStudioStore],
  templateUrl: './schema-studio.page.html',
})
export class SchemaStudioPage implements OnInit {
  readonly store = inject(SchemaStudioStore);
  private readonly fb = inject(FormBuilder);
  private readonly confirm = inject(ConfirmDialogService);
  private readonly formErrors = inject(FormErrorService);

  readonly tab = signal('workspace');
  readonly classModal = signal(false);
  readonly propModal = signal(false);
  readonly publishModal = signal(false);
  readonly schemaModal = signal(false);
  readonly schemaModalMode = signal<'create' | 'edit' | 'extract'>('create');
  readonly editingSchema = signal<SchemaRead | null>(null);
  readonly editingProp = signal<PropertyRead | null>(null);
  changeLog = '';

  readonly classForm = this.fb.nonNullable.group({
    label: ['', Validators.required],
    local_name: [''],
    description: [''],
  });

  readonly propForm = this.fb.nonNullable.group({
    label: ['', Validators.required],
    kind: ['data' as 'data' | 'object'],
    datatype: ['xsd:string'],
    range_class_id: [''],
    required: [false],
    multi: [false],
  });

  readonly schemaForm = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(128)]],
    createNew: [true],
  });

  constructor() {
    effect(() => {
      const err = this.formErrors.lastError();
      if (!err) return;
      this.classForm.get(err.field)?.setErrors({ server: err.message });
      this.propForm.get(err.field)?.setErrors({ server: err.message });
      this.schemaForm.get(err.field)?.setErrors({ server: err.message });
    });
  }

  ngOnInit(): void {
    this.store.loadSchemas();
    this.store.loadSourceFiles();
    this.store.loadModels();
  }

  onTabChange(next: string): void {
    this.tab.set(next);
    // 切到管理页时刷新列表，保证与工作区当前 Schema 名称/计数一致
    if (next === 'manage') this.store.reloadListKeepingSelection();
  }

  openInWorkspace(id: string): void {
    this.store.selectSchema(id);
    this.tab.set('workspace');
  }

  schemaModalTitle(): string {
    const mode = this.schemaModalMode();
    if (mode === 'create') return '新建 Schema';
    if (mode === 'edit') return '编辑 Schema 名称';
    return '开始抽取';
  }

  openCreateSchema(): void {
    this.schemaModalMode.set('create');
    this.editingSchema.set(null);
    this.schemaForm.reset({ name: '新建 Schema', createNew: true });
    this.schemaModal.set(true);
  }

  openEditSchema(s?: SchemaRead | null): void {
    const target = s ?? this.store.current();
    if (!target) return;
    this.schemaModalMode.set('edit');
    this.editingSchema.set(target);
    this.schemaForm.reset({ name: target.name, createNew: false });
    this.schemaModal.set(true);
  }

  openExtractModal(): void {
    const current = this.store.current();
    const suggested = this.store.suggestedExtractName();
    // 无当前 Schema，或已有内容时默认新建，避免覆盖
    const preferNew = !current || (current.class_count ?? 0) > 0;
    this.schemaModalMode.set('extract');
    this.editingSchema.set(current);
    this.schemaForm.reset({
      name: preferNew ? suggested : (current?.name || suggested),
      createNew: preferNew,
    });
    this.schemaModal.set(true);
  }

  saveSchemaModal(): void {
    if (this.schemaForm.invalid) {
      this.schemaForm.markAllAsTouched();
      return;
    }
    const v = this.schemaForm.getRawValue();
    const name = v.name.trim();
    const mode = this.schemaModalMode();

    if (mode === 'create') {
      this.store.createSchema(name);
      this.schemaModal.set(false);
      return;
    }
    if (mode === 'edit') {
      const target = this.editingSchema() ?? this.store.current();
      if (!target) return;
      this.store.renameSchema(target.id, name, () => this.schemaModal.set(false));
      return;
    }
    // extract：无当前 Schema 时强制新建
    const createNew = !this.store.current() || v.createNew;
    this.schemaModal.set(false);
    this.store.startExtract({ name, createNew });
  }

  onToggleFile(id: string, e: Event): void {
    const checked = (e.target as HTMLInputElement).checked;
    this.store.toggleFile(id, checked);
  }

  fileStatusLabel(status: string): string {
    return ({ ready: '已就绪', parsing: '解析中', pending: '待处理', failed: '失败' } as Record<string, string>)[status] || status;
  }

  selectedClassLabel(): string {
    const id = this.store.selectedClassId();
    return this.store.classes().find((c) => c.id === id)?.label || '';
  }

  openClassModal(): void {
    this.classForm.reset({ label: '', local_name: '', description: '' });
    this.classModal.set(true);
  }

  saveClass(): void {
    if (this.classForm.invalid) { this.classForm.markAllAsTouched(); return; }
    this.store.addClass(this.classForm.getRawValue());
    this.classModal.set(false);
  }

  openPropModal(prop?: PropertyRead): void {
    this.editingProp.set(prop ?? null);
    if (prop) {
      this.propForm.reset({
        label: prop.label, kind: prop.kind, datatype: prop.datatype || 'xsd:string',
        range_class_id: prop.range_class_id || '', required: prop.required, multi: prop.multi,
      });
    } else {
      this.propForm.reset({ label: '', kind: 'data', datatype: 'xsd:string', range_class_id: '', required: false, multi: false });
    }
    this.propModal.set(true);
  }

  saveProp(): void {
    if (this.propForm.invalid) { this.propForm.markAllAsTouched(); return; }
    const v = this.propForm.getRawValue();
    const body = {
      label: v.label,
      kind: v.kind,
      datatype: v.kind === 'data' ? v.datatype : null,
      range_class_id: v.kind === 'object' ? (v.range_class_id || null) : null,
      required: v.required,
      multi: v.multi,
    };
    const edit = this.editingProp();
    if (edit) this.store.updateProperty(edit.id, body);
    else this.store.addProperty(body);
    this.propModal.set(false);
  }

  async deleteProp(p: PropertyRead): Promise<void> {
    const ok = await this.confirm.confirm({ title: '删除属性', message: `删除「${p.label}」？`, danger: true, confirmText: '删除' });
    if (ok) this.store.deleteProperty(p.id);
  }

  async deleteSchema(s: SchemaRead): Promise<void> {
    const ok = await this.confirm.confirm({ title: '删除 Schema', message: `删除「${s.name}」？`, danger: true, confirmText: '删除' });
    if (ok) this.store.deleteSchema(s.id);
  }

  onImport(e: Event): void {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (file) this.store.importTtl(file);
    (e.target as HTMLInputElement).value = '';
  }
}
