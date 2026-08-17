import { Component, Input } from '@angular/core';
import { NgClass } from '@angular/common';

@Component({
  selector: 'ui-button',
  standalone: true,
  imports: [NgClass],
  template: `<button [type]="type" class="btn" [ngClass]="[variant, size]" [disabled]="disabled"><ng-content /></button>`,
})
export class ButtonComponent {
  @Input() variant: string = 'btn-secondary';
  @Input() size: string = '';
  @Input() type: 'button' | 'submit' = 'button';
  @Input() disabled = false;
}
