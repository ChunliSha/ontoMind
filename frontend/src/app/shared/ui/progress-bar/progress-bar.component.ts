import { Component, computed, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';

@Component({
  selector: 'ui-progress-bar',
  standalone: true,
  imports: [DecimalPipe],
  template: `
    <div class="om-progress">
      @if (label()) {
        <div class="om-progress-meta">
          <span>{{ label() }}</span>
          <span>{{ pct() | number:'1.0-0' }}%</span>
        </div>
      }
      <div class="om-progress-track">
        <div class="om-progress-fill" [style.width.%]="pct()"></div>
      </div>
    </div>
  `,
  styles: [`
    :host { display: block; }
    .om-progress { display: flex; flex-direction: column; gap: 8px; }
    .om-progress-meta { display: flex; justify-content: space-between; gap: 12px; font-size: 12.5px; color: var(--text-500); line-height: 1.45; }
    .om-progress-meta span:first-child { flex: 1; min-width: 0; }
    .om-progress-meta span:last-child { flex-shrink: 0; font-variant-numeric: tabular-nums; }
    .om-progress-track { height: 8px; background: var(--neutral-soft); border-radius: 99px; overflow: hidden; }
    .om-progress-fill { height: 100%; width: 0; background: linear-gradient(90deg, var(--accent), var(--inst-c)); border-radius: 99px; transition: width .25s ease; }
  `],
})
export class ProgressBarComponent {
  readonly progress = input(0);
  readonly label = input('进度');
  readonly pct = computed(() => {
    const n = Number(this.progress());
    return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
  });
}
