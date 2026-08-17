import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./features/dashboard/dashboard.page').then(m => m.DashboardPage) },
  { path: 'data/structured', loadComponent: () => import('./features/data-integration/structured/structured.page').then(m => m.StructuredPage) },
  { path: 'data/unstructured', loadComponent: () => import('./features/data-integration/unstructured/unstructured.page').then(m => m.UnstructuredPage) },
  { path: 'schema', loadComponent: () => import('./features/schema-studio/schema-studio.page').then(m => m.SchemaStudioPage) },
  { path: 'models', loadComponent: () => import('./features/llm-models/llm-models.page').then(m => m.LlmModelsPage) },
  { path: 'extraction/instances', loadComponent: () => import('./features/extraction/instance-extraction/instance-extraction.page').then(m => m.InstanceExtractionPage) },
  { path: 'extraction/business-logic', loadComponent: () => import('./features/extraction/business-logic/business-logic.page').then(m => m.BusinessLogicPage) },
  { path: 'graph', loadComponent: () => import('./features/graph-explorer/graph-explorer.page').then(m => m.GraphExplorerPage) },
  { path: '**', redirectTo: '' },
];
