import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormsModule } from '@angular/forms';
import { LlmModelsStore } from './llm-models.store';
import { BadgeComponent } from '../../shared/ui/badge/badge.component';
import { ModalComponent } from '../../shared/ui/modal/modal.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state/empty-state.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { LucideDynamicIcon } from '@lucide/angular';
import { ConfirmDialogService } from '../../core/services/confirm-dialog.service';
import { LlmModelRead, LlmPreset, LlmProvider, LlmSource } from '../../core/models/llm';

@Component({
  selector: 'app-llm-models-page',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    FormsModule,
    BadgeComponent,
    ModalComponent,
    EmptyStateComponent,
    RelativeTimePipe,
    LucideDynamicIcon,
  ],
  providers: [LlmModelsStore],
  templateUrl: './llm-models.page.html',
})
export class LlmModelsPage implements OnInit {
  readonly store = inject(LlmModelsStore);
  private readonly fb = inject(FormBuilder);
  private readonly confirm = inject(ConfirmDialogService);

  readonly modalOpen = signal(false);
  readonly editing = signal<LlmModelRead | null>(null);
  readonly presetModalOpen = signal(false);

  readonly form = this.fb.nonNullable.group({
    name: ['', Validators.required],
    source: ['cloud' as LlmSource, Validators.required],
    provider: ['openai' as LlmProvider, Validators.required],
    api_base: [''],
    api_key: [''],
    model_name: ['', Validators.required],
    is_default: [false],
  });

  ngOnInit(): void {
    this.store.load();
    this.store.loadPresets();
  }

  openCreate(preset?: LlmPreset): void {
    this.editing.set(null);
    this.form.reset({
      name: preset?.name ?? '',
      source: preset?.source ?? 'cloud',
      provider: preset?.provider ?? 'openai',
      api_base: preset?.api_base ?? '',
      api_key: '',
      model_name: preset?.model_name ?? '',
      is_default: false,
    });
    this.presetModalOpen.set(false);
    this.modalOpen.set(true);
  }

  openEdit(row: LlmModelRead): void {
    this.editing.set(row);
    this.form.reset({
      name: row.name,
      source: row.source,
      provider: row.provider,
      api_base: row.api_base ?? '',
      api_key: '',
      model_name: row.model_name,
      is_default: row.is_default,
    });
    this.modalOpen.set(true);
  }

  save(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const edit = this.editing();
    if (edit) {
      const body: any = {
        name: v.name,
        source: v.source,
        provider: v.provider,
        api_base: v.api_base || null,
        model_name: v.model_name,
        is_default: v.is_default,
      };
      if (v.api_key) body.api_key = v.api_key;
      this.store.update(edit.id, body, () => this.modalOpen.set(false));
    } else {
      this.store.create(
        {
          name: v.name,
          source: v.source,
          provider: v.provider,
          api_base: v.api_base || null,
          api_key: v.api_key || null,
          model_name: v.model_name,
          is_default: v.is_default,
        },
        () => this.modalOpen.set(false),
      );
    }
  }

  async remove(row: LlmModelRead): Promise<void> {
    const ok = await this.confirm.confirm({
      title: '删除模型',
      message: `确定删除「${row.name}」？`,
      danger: true,
      confirmText: '删除',
    });
    if (ok) this.store.remove(row.id);
  }

  providerLabel(p: string): string {
    const map: Record<string, string> = {
      openai: 'OpenAI',
      azure_openai: 'Azure OpenAI',
      deepseek: 'DeepSeek',
      qwen: '通义千问',
      zhipu: '智谱 GLM',
      moonshot: 'Moonshot',
      ollama: 'Ollama',
      vllm: 'vLLM',
      local_openai: '本地 OpenAI 兼容',
      custom: '自定义',
      mock: 'Mock',
    };
    return map[p] || p;
  }

  statusBadge(s: string): 'b-success' | 'b-warning' | 'b-danger' | 'b-neutral' {
    if (s === 'active') return 'b-success';
    if (s === 'failed') return 'b-danger';
    if (s === 'disabled') return 'b-neutral';
    return 'b-warning';
  }

  statusLabel(s: string): string {
    return ({ active: '启用', failed: '失败', disabled: '禁用' } as Record<string, string>)[s] || s;
  }
}
