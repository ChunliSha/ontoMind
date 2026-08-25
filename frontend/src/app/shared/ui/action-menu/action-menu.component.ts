import { Component, EventEmitter, HostListener, Input, Output } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

export interface ActionMenuItem { id: string; label: string; danger?: boolean; disabled?: boolean; }

@Component({
  selector: 'ui-action-menu',
  standalone: true,
  imports: [LucideDynamicIcon],
  template: `
    <div class="action-menu-wrap">
      <button class="icon-btn" type="button" (click)="toggle($event)">
        <svg lucideIcon="more-horizontal" [size]="16"></svg>
      </button>
      @if (open) {
        <div class="action-menu" [style.top.px]="menuTop" [style.right.px]="menuRight">
          @for (item of items; track item.id) {
            <button type="button" [class.danger]="item.danger" [disabled]="item.disabled" (click)="pick(item, $event)">{{ item.label }}</button>
          }
        </div>
      }
    </div>
  `,
  styles: [`
    .action-menu-wrap { position: relative; display: inline-block; }
    .action-menu {
      position: fixed; z-index: 80; min-width: 160px;
      background: var(--card); border: 1px solid var(--border); border-radius: var(--r-md);
      box-shadow: var(--shadow-md); padding: 6px; display: flex; flex-direction: column; gap: 2px;
    }
    .action-menu button { border: 0; background: transparent; text-align: left; padding: 8px 10px; border-radius: 6px; color: var(--text-700); font-size: 13px; }
    .action-menu button:hover { background: var(--surface); }
    .action-menu button.danger { color: var(--danger); }
    .action-menu button:disabled { opacity: .45; }
  `],
})
export class ActionMenuComponent {
  @Input() items: ActionMenuItem[] = [];
  @Output() action = new EventEmitter<string>();
  open = false;
  menuTop = 0;
  menuRight = 0;
  toggle(e: MouseEvent): void {
    e.stopPropagation();
    this.open = !this.open;
    if (!this.open) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const openUp = window.innerHeight - r.bottom < 240;
    this.menuTop = openUp ? Math.max(8, r.top - 8 - this.items.length * 36) : r.bottom + 4;
    this.menuRight = Math.max(8, window.innerWidth - r.right);
  }
  pick(item: ActionMenuItem, e: MouseEvent): void {
    e.stopPropagation();
    if (item.disabled) return;
    this.open = false;
    this.action.emit(item.id);
  }
  @HostListener('document:click') close(): void { this.open = false; }
}
