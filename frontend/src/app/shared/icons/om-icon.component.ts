import { Component, Input } from '@angular/core';
import { LucideDynamicIcon, LucideIconInput } from '@lucide/angular';

/** Thin wrapper so feature modules can import a local standalone component. */
@Component({
  selector: 'om-icon',
  standalone: true,
  imports: [LucideDynamicIcon],
  template: `<svg [lucideIcon]="name" [size]="size"></svg>`,
})
export class OmIconComponent {
  @Input({ required: true }) name!: LucideIconInput;
  @Input() size: number | string = 16;
}
