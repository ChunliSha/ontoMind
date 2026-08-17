import { Component, Input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'ui-stat-card',
  standalone: true,
  imports: [LucideDynamicIcon],
  template: `
    <div class="stat-card">
      <div class="stat-top">
        <div class="stat-icon" [class]="iconClass"><svg [lucideIcon]="icon" [size]="18"></svg></div>
        @if (trend !== undefined && trend !== null) {
          <span class="stat-trend" [style.color]="trend === '--' ? 'var(--text-400)' : null">
            @if (trend !== '--') { <svg lucideIcon="arrow-up-right" [size]="11"></svg> }
            {{ trend }}
          </span>
        }
      </div>
      <div class="stat-num">{{ value }}</div>
      <div class="stat-label">{{ label }}</div>
    </div>
  `,
})
export class StatCardComponent {
  @Input() icon = 'database';
  @Input() iconClass = 'c1';
  @Input() value: string | number = 0;
  @Input() label = '';
  @Input() trend: string | number | null | undefined;
}
