import { Component, EventEmitter, Input, Output } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'ui-dropzone',
  standalone: true,
  imports: [LucideDynamicIcon],
  template: `
    <div class="dropzone" [class.dragover]="dragover"
      (dragover)="onDragOver($event)" (dragleave)="dragover=false"
      (drop)="onDrop($event)" (click)="fileInput.click()">
      <svg lucideIcon="upload" [size]="28"></svg>
      <div class="dz-title">拖拽文件到此处，或点击选择文件</div>
      <div class="dz-sub">{{ hint }}</div>
      <input #fileInput type="file" hidden [multiple]="multiple" [accept]="accept" (change)="onPick($event)" />
    </div>
  `,
})
export class DropzoneComponent {
  @Input() multiple = true;
  @Input() accept = '.pdf,.doc,.docx,.txt,.md,.xlsx,.xls,.csv';
  @Input() hint = '支持 PDF / DOCX / TXT / MD / XLSX，单个文件不超过 200MB';
  @Output() filesSelected = new EventEmitter<File[]>();
  dragover = false;
  onDragOver(e: DragEvent): void { e.preventDefault(); this.dragover = true; }
  onDrop(e: DragEvent): void {
    e.preventDefault(); this.dragover = false;
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length) this.filesSelected.emit(files);
  }
  onPick(e: Event): void {
    const input = e.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    if (files.length) this.filesSelected.emit(files);
    input.value = '';
  }
}
