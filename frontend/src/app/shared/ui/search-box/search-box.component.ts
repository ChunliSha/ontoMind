import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'ui-search-box',
  standalone: true,
  imports: [FormsModule, LucideDynamicIcon],
  template: `
    <div class="search-box">
      <svg lucideIcon="search" [size]="15"></svg>
      <input [placeholder]="placeholder" [ngModel]="value" (ngModelChange)="onChange($event)" />
    </div>
  `,
})
export class SearchBoxComponent {
  @Input() placeholder = '鎼滅储';
  @Input() value = '';
  @Output() valueChange = new EventEmitter<string>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  onChange(v: string): void {
    this.value = v;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.valueChange.emit(v), 250);
  }
}
