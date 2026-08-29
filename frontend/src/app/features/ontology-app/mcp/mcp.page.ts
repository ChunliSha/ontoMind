import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';
import { API_BASE_URL } from '../../../core/api/api-client';
import { McpApi, McpApiKey, McpApiKeyCreated, McpService, McpTool } from '../../../core/api/mcp.api';
import { OntologyModelsApi } from '../../../core/api/ontology-models.api';
import { OntologyModelRead } from '../../../core/models/ontology-model';
import { ConfirmDialogService } from '../../../core/services/confirm-dialog.service';
import { ToastService } from '../../../core/services/toast.service';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { ModalComponent } from '../../../shared/ui/modal/modal.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';

@Component({
  selector: 'app-mcp-page',
  standalone: true,
  imports: [
    FormsModule,
    DatePipe,
    LucideDynamicIcon,
    BadgeComponent,
    EmptyStateComponent,
    ModalComponent,
    RelativeTimePipe,
  ],
  templateUrl: './mcp.page.html',
  styleUrl: './mcp.page.scss',
})
export class McpPage implements OnInit {
  private readonly mcpApi = inject(McpApi);
  private readonly modelsApi = inject(OntologyModelsApi);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmDialogService);

  readonly tab = signal<'keys' | 'services'>('keys');
  readonly keys = signal<McpApiKey[]>([]);
  readonly services = signal<McpService[]>([]);
  readonly tools = signal<McpTool[]>([]);
  readonly models = signal<OntologyModelRead[]>([]);
  readonly keyName = signal('');
  readonly creatingKey = signal(false);
  readonly revealedKey = signal<McpApiKeyCreated | null>(null);
  readonly modalOpen = signal(false);
  readonly saving = signal(false);
  readonly editingId = signal<string | null>(null);

  draftName = '';
  draftOntologyId = '';
  draftUrl = '';
  draftDescription = '';
  draftToolSelect = '';
  readonly draftTools = signal<string[]>([]);

  ngOnInit(): void {
    this.reloadKeys();
    this.reloadServices();
    this.mcpApi.listPublishedTools().subscribe({
      next: (rows) => this.tools.set(rows || []),
      error: () => this.tools.set([]),
    });
    this.modelsApi.list({ page: 1, page_size: 100, min_instances: 0 }).subscribe({
      next: (page) => this.models.set(page.items || []),
      error: () => this.models.set([]),
    });
  }

  onTab(id: string): void {
    this.tab.set(id === 'services' ? 'services' : 'keys');
  }

  reloadKeys(): void {
    this.mcpApi.listApiKeys().subscribe({
      next: (rows) => this.keys.set(rows || []),
      error: () => this.toast.error('无法加载 API Key'),
    });
  }

  reloadServices(): void {
    this.mcpApi.listServices().subscribe({
      next: (rows) => this.services.set(rows || []),
      error: () => this.toast.error('无法加载 MCP 服务'),
    });
  }

  createKey(): void {
    if (this.creatingKey()) return;
    this.creatingKey.set(true);
    this.mcpApi.createApiKey({ name: this.keyName().trim() }).subscribe({
      next: (created) => {
        this.creatingKey.set(false);
        this.keyName.set('');
        this.revealedKey.set(created);
        this.reloadKeys();
        this.toast.success('已生成新 Key，请立即复制保存');
      },
      error: () => {
        this.creatingKey.set(false);
        this.toast.error('生成 Key 失败');
      },
    });
  }

  async copyKey(): Promise<void> {
    const raw = this.revealedKey()?.api_key;
    if (!raw) return;
    try {
      await navigator.clipboard.writeText(raw);
      this.toast.success('已复制 API Key');
    } catch {
      this.toast.error('复制失败');
    }
  }

  async removeKey(row: McpApiKey): Promise<void> {
    const ok = await this.confirm.confirm({
      title: '删除 API Key',
      message: `删除「${row.name}」（${row.key_prefix}…）后将立即失效。`,
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;
    this.mcpApi.deleteApiKey(row.id).subscribe({
      next: () => {
        this.reloadKeys();
        this.toast.success('已删除');
      },
      error: () => this.toast.error('删除失败'),
    });
  }

  clientUrl(ontologyId?: string | null): string {
    const id = (ontologyId || '').trim();
    return id ? `${API_BASE_URL}/mcp?ontology_id=${id}` : `${API_BASE_URL}/mcp`;
  }

  openCreateService(): void {
    this.editingId.set(null);
    this.draftName = '';
    this.draftOntologyId = this.models()[0]?.id || '';
    this.draftUrl = this.clientUrl(this.draftOntologyId);
    this.draftDescription = '';
    this.draftToolSelect = '';
    this.draftTools.set([]);
    this.modalOpen.set(true);
  }

  openEditService(row: McpService): void {
    this.editingId.set(row.id);
    this.draftName = row.name || '';
    this.draftOntologyId = row.ontology_model_id || '';
    this.draftUrl = this.clientUrl(this.draftOntologyId) || row.url || '';
    this.draftDescription = row.description || '';
    this.draftToolSelect = '';
    this.draftTools.set([...(row.tool_names || [])]);
    this.modalOpen.set(true);
  }

  closeServiceModal(): void {
    this.modalOpen.set(false);
    this.editingId.set(null);
  }

  onDraftOntologyChange(id: string): void {
    this.draftOntologyId = id;
    this.draftUrl = this.clientUrl(id);
  }

  onToolSelect(name: string): void {
    if (!name) return;
    this.toggleTool(name, true);
    this.draftToolSelect = '';
  }

  toggleTool(name: string, checked: boolean): void {
    const cur = new Set(this.draftTools());
    if (checked) cur.add(name);
    else cur.delete(name);
    this.draftTools.set([...cur]);
  }

  toolChecked(name: string): boolean {
    return this.draftTools().includes(name);
  }

  saveService(): void {
    const name = this.draftName.trim();
    if (!name) {
      this.toast.error('请填写服务名称');
      return;
    }
    if (!this.draftOntologyId) {
      this.toast.error('请选择关联本体');
      return;
    }
    if (!this.draftTools().length) {
      this.toast.error('请至少选择一个 MCP 工具');
      return;
    }
    if (this.saving()) return;
    this.saving.set(true);
    const body = {
      name,
      ontology_model_id: this.draftOntologyId,
      url: this.draftUrl.trim() || this.clientUrl(this.draftOntologyId),
      tool_names: this.draftTools(),
      description: this.draftDescription.trim(),
    };
    const editId = this.editingId();
    const req = editId
      ? this.mcpApi.updateService(editId, body)
      : this.mcpApi.createService(body);
    req.subscribe({
      next: () => {
        this.saving.set(false);
        this.closeServiceModal();
        this.reloadServices();
        this.toast.success(editId ? 'MCP 服务已更新' : 'MCP 服务已创建');
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(editId ? '保存失败，请检查名称是否重复' : '创建失败，请检查名称是否重复');
      },
    });
  }

  async removeService(row: McpService): Promise<void> {
    const ok = await this.confirm.confirm({
      title: '删除 MCP 服务',
      message: `删除「${row.name}」？`,
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;
    this.mcpApi.deleteService(row.id).subscribe({
      next: () => {
        this.reloadServices();
        this.toast.success('已删除');
      },
      error: () => this.toast.error('删除失败'),
    });
  }

  async copyUrl(row: McpService): Promise<void> {
    const url = this.clientUrl(row.ontology_model_id) || row.url;
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      this.toast.success('已复制链接地址');
    } catch {
      this.toast.error('复制失败');
    }
  }

  async copyCursorConfig(row: McpService): Promise<void> {
    const snippet = JSON.stringify(
      {
        mcpServers: {
          [row.name]: {
            type: 'http',
            url: this.clientUrl(row.ontology_model_id),
            headers: { 'X-API-Key': '替换为你的 API Key' },
          },
        },
      },
      null,
      2,
    );
    try {
      await navigator.clipboard.writeText(snippet);
      this.toast.success('已复制 Cursor mcp.json 片段，请填入完整 API Key');
    } catch {
      this.toast.error('复制失败');
    }
  }
}
