import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';
import { CatalogInstance, TopologyNode } from '../../../core/models/topology';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';

@Component({
  selector: 'app-topology-inspector',
  standalone: true,
  imports: [FormsModule, EmptyStateComponent, LucideDynamicIcon],
  template: `
    @if (node) {
      <div class="insp-head">
        <h4>节点属性</h4>
        @if (closable) {
          <button class="icon-btn" type="button" title="关闭" (click)="close.emit()">
            <svg lucideIcon="x" [size]="14"></svg>
          </button>
        }
      </div>
      <div class="hint">
        本体类：{{ node.type }}
        @if (ungrounded) {
          <span class="custom-hint"> · 未挂载，请选择实例</span>
        } @else {
          · 已挂载
        }
      </div>
      <label>名称
        <input class="form-ctl" [value]="node.label" (blur)="labelBlur.emit($any($event.target).value)" />
      </label>
      <label>挂载实例
        <select class="form-ctl" [ngModel]="remountId" (ngModelChange)="remountIdChange.emit($event)">
          <option value="">自定义（不落地）</option>
          @for (inst of candidates; track inst.id) {
            <option [value]="inst.id">{{ inst.class_label }} · {{ inst.label }}</option>
          }
        </select>
      </label>
      <button class="btn btn-primary btn-sm" type="button" [disabled]="saving" (click)="remount.emit()">应用挂载</button>
      <label>判断内容
        <textarea class="form-ctl" rows="4"
          [value]="propText('judgementContent')"
          (blur)="propBlur.emit({ key: 'judgementContent', value: $any($event.target).value })"></textarea>
      </label>
      <label>分析
        <textarea class="form-ctl" rows="4"
          [value]="propText('step1Analysis')"
          (blur)="propBlur.emit({ key: 'step1Analysis', value: $any($event.target).value })"></textarea>
      </label>
      <label>描述
        <textarea class="form-ctl" rows="4"
          [value]="propText('description')"
          (blur)="propBlur.emit({ key: 'description', value: $any($event.target).value })"></textarea>
      </label>
    } @else {
      <ui-empty-state title="未选中节点" desc="点击画布中的节点可查看完整文案、改名称或挂载实例。虚线描边的是自定义节点。" />
    }
  `,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 10px; height: 100%; overflow: auto; }
    .insp-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    h4 { margin: 0; font-size: 14px; }
    label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--text-500); }
    .hint { font-size: 12px; color: var(--text-400); line-height: 1.45; }
    .custom-hint { color: #b45309; font-weight: 600; }
  `],
})
export class TopologyInspectorComponent {
  @Input() node: TopologyNode | null = null;
  @Input() ungrounded = false;
  @Input() candidates: CatalogInstance[] = [];
  @Input() remountId = '';
  @Input() saving = false;
  @Input() closable = false;
  @Output() remountIdChange = new EventEmitter<string>();
  @Output() remount = new EventEmitter<void>();
  @Output() labelBlur = new EventEmitter<string>();
  @Output() propBlur = new EventEmitter<{ key: string; value: string }>();
  @Output() close = new EventEmitter<void>();

  propText(key: string): string {
    const v = this.node?.properties?.[key];
    if (v == null) return '';
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }
}
