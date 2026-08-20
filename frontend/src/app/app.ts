import { Component, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter, map, startWith } from 'rxjs/operators';
import { toSignal } from '@angular/core/rxjs-interop';
import { LucideDynamicIcon } from '@lucide/angular';
import { ToastService } from './core/services/toast.service';
import { ConfirmDialogService } from './core/services/confirm-dialog.service';
import { NgClass } from '@angular/common';

const TITLES: Record<string, string> = {
  '/': '快速指引',
  '/data/structured': '结构化数据管理',
  '/data/unstructured': '非结构化数据管理',
  '/schema': 'Schema 抽取与设计',
  '/models': '模型管理',
  '/extraction/instances': '本体抽取',
  '/extraction/business-logic': '业务逻辑抽取',
  '/extraction/business-logic/workspace': '业务逻辑管理',
  '/graph': '图谱探索',
};

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, LucideDynamicIcon, NgClass],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly router = inject(Router);
  readonly toast = inject(ToastService);
  readonly confirm = inject(ConfirmDialogService);

  readonly dataOpen = signal(true);
  readonly extractOpen = signal(true);

  private readonly currentUrl = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects.split('?')[0] || '/'),
      startWith(this.router.url.split('?')[0] || '/'),
    ),
    { initialValue: '/' },
  );

  readonly pageTitle = computed(() => TITLES[this.currentUrl()] ?? 'OntoMind');
}
