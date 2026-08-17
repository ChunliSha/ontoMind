import { Component, Input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'ui-pipeline-step',
  standalone: true,
  imports: [LucideDynamicIcon, RouterLink],
  template: `
    <div class="pl-step">
      <div class="pl-head"><span class="pl-num">{{ num }}</span>
        <div class="pl-icon"><svg [lucideIcon]="icon" [size]="18"></svg></div>
      </div>
      <h3>{{ title }}</h3>
      <p class="pl-desc">{{ desc }}</p>
      <a class="pl-link" [routerLink]="link">{{ linkText }} <svg lucideIcon="arrow-right" [size]="14"></svg></a>
    </div>
  `,
})
export class PipelineStepComponent {
  @Input() num = '01';
  @Input() icon = 'database';
  @Input() title = '';
  @Input() desc = '';
  @Input() link = '/';
  @Input() linkText = '鍓嶅線';
}
