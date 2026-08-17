import { Component, OnInit, effect, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { StructuredStore } from './structured.store';
import { SearchBoxComponent } from '../../../shared/ui/search-box/search-box.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { ModalComponent } from '../../../shared/ui/modal/modal.component';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { LucideDynamicIcon } from '@lucide/angular';
import { ConfirmDialogService } from '../../../core/services/confirm-dialog.service';
import { FormErrorService } from '../../../core/services/form-error.service';
import { DbSourcesApi } from '../../../core/api/db-sources.api';
import { ToastService } from '../../../core/services/toast.service';
import { DbSourceRead } from '../../../core/models/db-source';

@Component({
  selector: 'app-structured-page',
  standalone: true,
  imports: [ReactiveFormsModule, SearchBoxComponent, BadgeComponent, ModalComponent, EmptyStateComponent, RelativeTimePipe, LucideDynamicIcon],
  providers: [StructuredStore],
  templateUrl: './structured.page.html',
})
export class StructuredPage implements OnInit {
  readonly store = inject(StructuredStore);
  private readonly fb = inject(FormBuilder);
  private readonly confirm = inject(ConfirmDialogService);
  private readonly formErrors = inject(FormErrorService);
  private readonly api = inject(DbSourcesApi);
  private readonly toast = inject(ToastService);

  readonly dbModalOpen = signal(false);
  readonly tablesModalOpen = signal(false);
  readonly editing = signal<DbSourceRead | null>(null);
  readonly selectedTableIds = signal<Set<string>>(new Set());

  readonly form = this.fb.nonNullable.group({
    name: ['', Validators.required],
    db_type: ['postgres' as 'postgres' | 'mysql' | 'gaussdb', Validators.required],
    host: ['', Validators.required],
    port: [5432, Validators.required],
    database_name: ['', Validators.required],
    username: ['', Validators.required],
    password: ['', Validators.required],
  });

  constructor() {
    effect(() => {
      const err = this.formErrors.lastError();
      if (!err) return;
      this.form.get(err.field)?.setErrors({ server: err.message });
    });
  }

  ngOnInit(): void { this.store.load(); }

  onSearch(v: string): void { this.store.search.set(v); this.store.load(); }

  openCreate(): void {
    this.editing.set(null);
    this.form.reset({ name: '', db_type: 'postgres', host: '', port: 5432, database_name: '', username: '', password: '' });
    this.dbModalOpen.set(true);
  }

  openEdit(row: DbSourceRead): void {
    this.editing.set(row);
    this.form.reset({
      name: row.name, db_type: row.db_type, host: row.host, port: row.port,
      database_name: row.database_name, username: row.username, password: '',
    });
    this.form.controls.password.clearValidators();
    this.form.controls.password.updateValueAndValidity();
    this.dbModalOpen.set(true);
  }

  testConn(): void {
    const v = this.form.getRawValue();
    const edit = this.editing();
    if (edit) {
      this.api.testConnection(edit.id).subscribe({ next: (r) => this.toast.success(r.ok ? '连接成功' : (r.message || '失败')) });
    } else {
      this.api.testDraft(v).subscribe({ next: (r) => this.toast.success(r.ok ? '连接成功' : (r.message || '失败')) });
    }
  }

  save(): void {
    if (this.form.invalid) { this.form.markAllAsTouched(); return; }
    const v = this.form.getRawValue();
    const edit = this.editing();
    if (edit) {
      const body: any = { ...v };
      if (!body.password) delete body.password;
      this.store.update(edit.id, body, () => this.dbModalOpen.set(false));
    } else {
      this.store.create(v, () => this.dbModalOpen.set(false));
    }
  }

  async remove(row: DbSourceRead): Promise<void> {
    const ok = await this.confirm.confirm({ title: '删除连接', message: `确定删除「${row.name}」？`, danger: true, confirmText: '删除' });
    if (ok) this.store.remove(row.id);
  }

  viewTables(row: DbSourceRead): void {
    this.store.loadTables(row);
    this.selectedTableIds.set(new Set());
    this.tablesModalOpen.set(true);
  }

  toggleTable(id: string, checked: boolean): void {
    const next = new Set(this.selectedTableIds());
    if (checked) next.add(id); else next.delete(id);
    this.selectedTableIds.set(next);
  }

  confirmTables(): void {
    this.store.saveTableSelection([...this.selectedTableIds()], () => this.tablesModalOpen.set(false));
  }

  statusBadge(status: string): string {
    if (status === 'connected') return 'b-success';
    if (status === 'failed') return 'b-danger';
    if (status === 'syncing') return 'b-warning';
    return 'b-neutral';
  }

  statusLabel(status: string): string {
    return ({ connected: '已连接', failed: '失败', syncing: '同步中', pending: '待连接' } as any)[status] || status;
  }

  typeLabel(t: string): string {
    return ({ postgres: 'PostgreSQL', mysql: 'MySQL', gaussdb: 'GaussDB' } as any)[t] || t;
  }

  fieldError(name: string): string | null {
    const c = this.form.get(name);
    if (!c?.errors || !c.touched) return null;
    if (c.errors['server']) return c.errors['server'];
    if (c.errors['required']) return '必填';
    return null;
  }
}
