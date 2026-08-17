import { Component, Input, inject } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';
import { ToastService } from '../../../core/services/toast.service';

@Component({
  selector: 'ui-code-block',
  standalone: true,
  imports: [LucideDynamicIcon],
  template: `
    <div class="code-block">
      <div class="code-block-head">
        <span>{{ title }}</span>
        <button class="btn btn-ghost btn-sm" type="button" (click)="copy()">
          <svg lucideIcon="copy" [size]="14"></svg>复制
        </button>
      </div>
      <pre><code>{{ code }}</code></pre>
    </div>
  `,
})
export class CodeBlockComponent {
  private toast = inject(ToastService);
  @Input() code = '';
  @Input() title = 'JSON';

  async copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.code);
      this.toast.success('已复制到剪贴板');
    } catch {
      this.toast.error('复制失败');
    }
  }
}
