import { HttpContextToken } from '@angular/common/http';

/** When true, the error interceptor skips toasts (used by background polls). */
export const SILENT_ERROR = new HttpContextToken<boolean>(() => false);
