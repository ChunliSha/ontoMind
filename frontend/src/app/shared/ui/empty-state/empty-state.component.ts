import { Component, Input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'ui-empty-state',
  standalone: true,
  imports: [LucideDynamicIcon],
  template: `
    <div class="empty-state">
      <svg [lucideIcon]="icon" [size]="32"></svg>
      <div class="empty-title">{{ title }}</div>
      <div class="empty-desc">{{ desc }}</div>
      <ng-content />
    </div>
  `,
})
export class EmptyStateComponent {
  @Input() icon = 'search';
  @Input() title = '鏆傛棤鏁版嵁';
  @Input() desc = '';
}
