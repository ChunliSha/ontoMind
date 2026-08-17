import { Component, OnInit, inject } from '@angular/core';
import { DashboardStore } from './dashboard.store';
import { StatCardComponent } from '../../shared/ui/stat-card/stat-card.component';
import { PipelineStepComponent } from '../../shared/ui/pipeline-step/pipeline-step.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';

@Component({
  selector: 'app-dashboard-page',
  standalone: true,
  imports: [StatCardComponent, PipelineStepComponent, RelativeTimePipe],
  providers: [DashboardStore],
  templateUrl: './dashboard.page.html',
})
export class DashboardPage implements OnInit {
  readonly store = inject(DashboardStore);
  ngOnInit(): void { this.store.load(); }

  fmt(n: number | undefined | null): string {
    if (n == null) return '0';
    return n.toLocaleString('zh-CN');
  }
}
