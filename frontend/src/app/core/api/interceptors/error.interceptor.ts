import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { ErrorResponse } from '../../models/common';
import { FormErrorService } from '../../services/form-error.service';
import { ToastService } from '../../services/toast.service';
import { SILENT_ERROR } from '../silent-error';

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const toast = inject(ToastService);
  const formErrors = inject(FormErrorService);

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      if (req.context.get(SILENT_ERROR)) {
        return throwError(() => err);
      }
      const body = err.error as ErrorResponse | null;
      const detail = body?.error;

      if (detail?.field) {
        formErrors.emit({ field: detail.field, message: detail.message, code: detail.code });
      } else if (detail?.message) {
        toast.error(detail.message);
      } else if (err.status === 0) {
        toast.error('无法连接后端服务，请确认 API 已启动（http://127.0.0.1:8000）');
      } else {
        toast.error(err.message || '请求失败');
      }

      return throwError(() => err);
    }),
  );
};
