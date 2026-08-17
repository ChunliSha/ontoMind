import { Injectable, signal } from '@angular/core';

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmText?: string;
  danger?: boolean;
}

interface ConfirmState extends ConfirmOptions {
  open: boolean;
  resolve: ((ok: boolean) => void) | null;
}

@Injectable({ providedIn: 'root' })
export class ConfirmDialogService {
  readonly state = signal<ConfirmState>({
    open: false,
    title: '',
    message: '',
    confirmText: '确定',
    danger: false,
    resolve: null,
  });

  confirm(options: ConfirmOptions): Promise<boolean> {
    return new Promise((resolve) => {
      this.state.set({
        open: true,
        title: options.title,
        message: options.message,
        confirmText: options.confirmText ?? '确定',
        danger: options.danger ?? false,
        resolve,
      });
    });
  }

  answer(ok: boolean): void {
    const current = this.state();
    current.resolve?.(ok);
    this.state.set({ ...current, open: false, resolve: null });
  }
}
