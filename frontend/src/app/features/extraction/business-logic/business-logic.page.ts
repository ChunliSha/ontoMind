import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BusinessLogicStore } from './business-logic.store';
import { ProgressBarComponent } from '../../../shared/ui/progress-bar/progress-bar.component';
import { CodeBlockComponent } from '../../../shared/ui/code-block/code-block.component';
import { EmptyStateComponent } from '../../../shared/ui/empty-state/empty-state.component';
import { LucideDynamicIcon } from '@lucide/angular';

@Component({
  selector: 'app-business-logic-page',
  standalone: true,
  imports: [FormsModule, ProgressBarComponent, CodeBlockComponent, EmptyStateComponent, LucideDynamicIcon],
  providers: [BusinessLogicStore],
  templateUrl: './business-logic.page.html',
})
export class BusinessLogicPage implements OnInit {
  readonly store = inject(BusinessLogicStore);
  ngOnInit(): void { this.store.bootstrap(); }
}
