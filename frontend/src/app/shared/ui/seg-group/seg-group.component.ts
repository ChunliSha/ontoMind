import { Component, EventEmitter, Input, Output } from '@angular/core';
export interface SegOption { id: string; label: string; }

@Component({
  selector: 'ui-seg-group',
  standalone: true,
  template: `
    <div class="seg-group">
      @for (opt of options; track opt.id) {
        <button type="button" class="seg-btn" [class.active]="opt.id === value" (click)="valueChange.emit(opt.id)">{{ opt.label }}</button>
      }
    </div>
  `,
})
export class SegGroupComponent {
  @Input() options: SegOption[] = [];
  @Input() value = '';
  @Output() valueChange = new EventEmitter<string>();
}
