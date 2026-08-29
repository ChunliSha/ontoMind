import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';
import { forkJoin } from 'rxjs';
import { LlmModelsApi } from '../../../core/api/llm-models.api';
import { QaApi } from '../../../core/api/qa.api';
import { OntologyModelsApi } from '../../../core/api/ontology-models.api';
import { ConfirmDialogService } from '../../../core/services/confirm-dialog.service';
import { LlmModelRead } from '../../../core/models/llm';
import { OntologyModelRead } from '../../../core/models/ontology-model';
import { QaMessage, QaSessionSummary } from '../../../core/models/qa';
import { ToastService } from '../../../core/services/toast.service';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';

@Component({
  selector: 'app-knowledge-qa-page',
  standalone: true,
  imports: [FormsModule, LucideDynamicIcon, EmptyStateComponent, RelativeTimePipe],
  templateUrl: './qa.page.html',
  styleUrl: './qa.page.scss',
})
export class KnowledgeQaPage implements OnInit {
  private readonly qaApi = inject(QaApi);
  private readonly modelsApi = inject(OntologyModelsApi);
  private readonly llmApi = inject(LlmModelsApi);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmDialogService);

  readonly models = signal<OntologyModelRead[]>([]);
  readonly llms = signal<LlmModelRead[]>([]);
  readonly sessions = signal<QaSessionSummary[]>([]);
  readonly ontologyModelId = signal('');
  readonly llmModelId = signal('');
  readonly sessionId = signal('');
  readonly messages = signal<QaMessage[]>([]);
  readonly sending = signal(false);
  readonly question = signal('');
  readonly plan = signal<Record<string, unknown> | null>(null);
  readonly renamingId = signal('');
  readonly renameDraft = signal('');

  ngOnInit(): void {
    forkJoin({
      models: this.modelsApi.list({ page: 1, page_size: 100, min_instances: 0 }),
      llms: this.llmApi.listActive(),
    }).subscribe({
      next: ({ models, llms }) => {
        this.models.set(models.items || []);
        this.llms.set(llms || []);
        if (models.items[0] && !this.ontologyModelId()) {
          this.ontologyModelId.set(models.items[0].id);
        }
        const def = (llms || []).find((m) => m.is_default) || llms[0];
        if (def && !this.llmModelId()) this.llmModelId.set(def.id);
        this.loadSessions();
      },
      error: () => this.toast.error('无法加载本体模型或 LLM 列表'),
    });
  }

  onModelChange(id: string): void {
    this.ontologyModelId.set(id);
    this.sessionId.set('');
    this.messages.set([]);
    this.plan.set(null);
    this.loadSessions();
  }

  loadSessions(): void {
    const mid = this.ontologyModelId();
    if (!mid) {
      this.sessions.set([]);
      return;
    }
    this.qaApi.listSessions({ ontology_model_id: mid, page: 1, page_size: 100 }).subscribe({
      next: (page) => this.sessions.set(page.items || []),
      error: () => this.toast.error('无法加载历史会话'),
    });
  }

  newSession(): void {
    const mid = this.ontologyModelId();
    if (!mid) {
      this.toast.error('请先选择本体模型');
      return;
    }
    this.qaApi.createSession({ ontology_model_id: mid, model_id: this.llmModelId() || null }).subscribe({
      next: (s) => {
        this.sessionId.set(s.id);
        this.messages.set([]);
        this.plan.set(null);
        this.loadSessions();
      },
      error: () => this.toast.error('创建会话失败'),
    });
  }

  openSession(item: QaSessionSummary): void {
    if (this.renamingId() === item.id) return;
    if (this.sessionId() === item.id) return;
    this.qaApi.getSession(item.id).subscribe({
      next: (s) => {
        this.sessionId.set(s.id);
        this.ontologyModelId.set(s.ontology_model_id);
        if (s.llm_model_id) this.llmModelId.set(s.llm_model_id);
        this.messages.set(s.messages || []);
        this.plan.set(null);
      },
      error: () => this.toast.error('无法打开会话'),
    });
  }

  startRename(item: QaSessionSummary, ev: Event): void {
    ev.stopPropagation();
    this.renamingId.set(item.id);
    this.renameDraft.set(item.title === '新会话' ? '' : item.title);
  }

  commitRename(item: QaSessionSummary): void {
    if (this.renamingId() !== item.id) return;
    const title = this.renameDraft().trim();
    this.renamingId.set('');
    if (!title || title === item.title) return;
    this.qaApi.updateSession(item.id, { title }).subscribe({
      next: () => this.loadSessions(),
      error: () => this.toast.error('重命名失败'),
    });
  }

  cancelRename(): void {
    this.renamingId.set('');
  }

  async removeSession(item: QaSessionSummary, ev: Event): Promise<void> {
    ev.stopPropagation();
    const ok = await this.confirm.confirm({
      title: '删除会话',
      message: `删除「${item.title || '新会话'}」？消息无法恢复。`,
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;
    this.qaApi.deleteSession(item.id).subscribe({
      next: () => {
        if (this.sessionId() === item.id) {
          this.sessionId.set('');
          this.messages.set([]);
          this.plan.set(null);
        }
        this.loadSessions();
      },
      error: () => this.toast.error('删除失败'),
    });
  }

  send(): void {
    const q = this.question().trim();
    if (!q || this.sending()) return;
    const mid = this.ontologyModelId();
    if (!mid) {
      this.toast.error('请先选择本体模型');
      return;
    }
    this.sending.set(true);
    const go = (sid: string) => {
      this.messages.update((ms) => [...ms, { id: 'tmp-u', role: 'user', content: q }]);
      this.question.set('');
      this.qaApi.sendMessage(sid, { question: q, model_id: this.llmModelId() || null }).subscribe({
        next: (r) => {
          this.sessionId.set(r.session_id);
          this.messages.update((ms) => [
            ...ms.filter((m) => m.id !== 'tmp-u'),
            { id: 'u-' + Date.now(), role: 'user', content: q },
            {
              id: 'a-' + Date.now(),
              role: 'assistant',
              content: r.answer,
              evidences: r.evidences,
              plan: r.plan,
              tool_trace: r.tool_trace,
            },
          ]);
          this.plan.set(r.plan || null);
          this.sending.set(false);
          this.loadSessions();
        },
        error: () => {
          this.sending.set(false);
          this.toast.error('问答失败，请检查模型配置与本体实例');
        },
      });
    };
    if (this.sessionId()) {
      go(this.sessionId());
      return;
    }
    this.qaApi.createSession({ ontology_model_id: mid, model_id: this.llmModelId() || null }).subscribe({
      next: (s) => {
        this.sessionId.set(s.id);
        go(s.id);
      },
      error: () => {
        this.sending.set(false);
        this.toast.error('创建会话失败');
      },
    });
  }

  onKey(ev: KeyboardEvent): void {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      this.send();
    }
  }
}
