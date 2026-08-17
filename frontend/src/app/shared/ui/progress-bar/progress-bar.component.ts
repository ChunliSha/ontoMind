import { Component, Input } from '@angular/core';
import { DecimalPipe } from '@angular/common';

@Component({
  selector: 'ui-progress-bar',
  standalone: true,
  imports: [DecimalPipe],
  template: `
    <div class="progress-wrap">
      <div class="progress-meta"><span>{{ label }}</span><span>{{ clamped | number:'1.0-0' }}%</span></div>
      <div class="progress-track"><div class="progress-fill" [style.width.%]="clamped"></div></div>
    </div>
  `,
  styles: [`
    .progress-wrap { display:flex; flex-direction:column; gap:8px; }
    .progress-meta { display:flex; justify-content:space-between; font-size:12.5px; color:var(--text-500); }
    .progress-track { height:8px; background:var(--neutral-soft); border-radius:99px; overflow:hidden; }
    .progress-fill { height:100%; background:linear-gradient(90deg,var(--accent),var(--inst-c)); border-radius:99px; transition:width .25s ease; }
  `],
})
export class ProgressBarComponent {
  @Input() progress = 0;
  @Input() label = '进度';
  get clamped(): number { return Math.max(0, Math.min(100, Number(this.progress) || 0)); }
}
