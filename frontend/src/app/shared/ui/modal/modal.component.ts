import { Component, EventEmitter, Input, Output } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'ui-modal',
  standalone: true,
  imports: [LucideDynamicIcon],
  template: `
    @if (open) {
      <div class="modal-backdrop" (click)="onBackdrop($event)">
        <div class="modal" [style.width]="width" (click)="$event.stopPropagation()">
          <div class="modal-head">
            <h3>{{ title }}</h3>
            <button class="icon-btn" type="button" (click)="closed.emit()">
              <svg lucideIcon="x" [size]="16"></svg>
            </button>
          </div>
          <div class="modal-body"><ng-content /></div>
          <div class="modal-foot"><ng-content select="[footer]" /></div>
        </div>
      </div>
    }
  `,
})
export class ModalComponent {
  @Input() open = false;
  @Input() title = '';
  @Input() width = '520px';
  @Input() closeOnBackdrop = true;
  @Output() closed = new EventEmitter<void>();
  onBackdrop(e: MouseEvent): void {
    if (this.closeOnBackdrop && e.target === e.currentTarget) this.closed.emit();
  }
}
