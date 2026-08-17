import { Injectable, signal } from '@angular/core';

export interface FormFieldError {
  field: string;
  message: string;
  code?: string;
}

@Injectable({ providedIn: 'root' })
export class FormErrorService {
  readonly lastError = signal<FormFieldError | null>(null);

  emit(error: FormFieldError): void {
    this.lastError.set(error);
  }

  clear(): void {
    this.lastError.set(null);
  }
}
