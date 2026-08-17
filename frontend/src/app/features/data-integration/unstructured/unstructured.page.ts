import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { UnstructuredStore } from './unstructured.store';
import { DropzoneComponent } from '../../../shared/ui/dropzone/dropzone.component';
import { SearchBoxComponent } from '../../../shared/ui/search-box/search-box.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { ActionMenuComponent, ActionMenuItem } from '../../../shared/ui/action-menu/action-menu.component';
import { ModalComponent } from '../../../shared/ui/modal/modal.component';
import { CodeBlockComponent } from '../../../shared/ui/code-block/code-block.component';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { FileSizePipe } from '../../../shared/pipes/file-size.pipe';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { LucideDynamicIcon } from '@lucide/angular';
import { ConfirmDialogService } from '../../../core/services/confirm-dialog.service';
import { FilesApi } from '../../../core/api/files.api';
import { FileRead } from '../../../core/models/file';
import { ToastService } from '../../../core/services/toast.service';

@Component({
  selector: 'app-unstructured-page',
  standalone: true,
  imports: [FormsModule, DropzoneComponent, SearchBoxComponent, BadgeComponent, ActionMenuComponent, ModalComponent, CodeBlockComponent, EmptyStateComponent, FileSizePipe, RelativeTimePipe, LucideDynamicIcon],
  providers: [UnstructuredStore],
  templateUrl: './unstructured.page.html',
})
export class UnstructuredPage implements OnInit {
  readonly store = inject(UnstructuredStore);
  private readonly confirm = inject(ConfirmDialogService);
  private readonly api = inject(FilesApi);
  private readonly toast = inject(ToastService);

  readonly renameOpen = signal(false);
  readonly editOpen = signal(false);
  readonly sqlOpen = signal(false);
  readonly active = signal<FileRead | null>(null);
  renameValue = '';
  editText = '';
  sqlDdl = '';

  menuItems: ActionMenuItem[] = [
    { id: 'std-md', label: '转标准 MD' },
    { id: 'onto-md', label: '转本体 MD' },
    { id: 'rename', label: '重命名' },
    { id: 'edit', label: '编辑' },
    { id: 'sql', label: '构建表 SQL' },
    { id: 'delete', label: '删除', danger: true },
  ];

  ngOnInit(): void { this.store.load(); }

  onSearch(v: string): void { this.store.search.set(v); this.store.load(); }

  async onAction(file: FileRead, action: string): Promise<void> {
    this.active.set(file);
    if (action === 'std-md') this.store.convertMd(file.id, false);
    if (action === 'onto-md') this.store.convertMd(file.id, true);
    if (action === 'rename') { this.renameValue = file.name; this.renameOpen.set(true); }
    if (action === 'edit') {
      this.api.get(file.id).subscribe({
        next: (f) => { this.editText = f.extracted_text || ''; this.editOpen.set(true); },
      });
    }
    if (action === 'sql') {
      this.api.buildTableSql(file.id).subscribe({
        next: (r) => { this.sqlDdl = r.ddl; this.sqlOpen.set(true); },
      });
    }
    if (action === 'delete') {
      const ok = await this.confirm.confirm({ title: '删除文件', message: `确定删除「${file.name}」？`, danger: true, confirmText: '删除' });
      if (ok) this.store.remove(file.id);
    }
  }

  saveRename(): void {
    const f = this.active();
    if (!f || !this.renameValue.trim()) return;
    this.store.rename(f.id, this.renameValue.trim());
    this.renameOpen.set(false);
  }

  saveEdit(): void {
    const f = this.active();
    if (!f) return;
    this.store.updateText(f.id, this.editText);
    this.editOpen.set(false);
  }

  materialize(): void {
    const f = this.active();
    if (!f) return;
    this.api.materializeTable(f.id, this.sqlDdl).subscribe({
      next: () => { this.toast.success('表已创建'); this.sqlOpen.set(false); },
    });
  }

  statusBadge(s: string): string {
    return ({ ready: 'b-success', parsing: 'b-warning', pending: 'b-neutral', failed: 'b-danger' } as any)[s] || 'b-neutral';
  }
  statusLabel(s: string): string {
    return ({ ready: '已就绪', parsing: '解析中', pending: '待解析', failed: '失败' } as any)[s] || s;
  }
}
