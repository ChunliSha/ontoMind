import { Component } from '@angular/core';

@Component({
  selector: 'ui-data-table',
  standalone: true,
  template: `
    <div class="panel">
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><ng-content select="[header]" /></tr></thead>
          <tbody><ng-content /></tbody>
        </table>
      </div>
    </div>
  `,
})
export class DataTableComponent {}
