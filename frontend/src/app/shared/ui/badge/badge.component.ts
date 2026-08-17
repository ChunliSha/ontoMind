import { Component, Input } from '@angular/core';
import { NgClass } from '@angular/common';

@Component({
  selector: 'ui-badge',
  standalone: true,
  imports: [NgClass],
  template: `<span class="badge" [ngClass]="variant"><ng-content /></span>`,
})
export class BadgeComponent {
  @Input() variant: string = 'b-neutral';
}
