import type { ErrorCode } from "@wotao/contracts";

export class AppError extends Error {
  readonly statusCode: number;
  readonly errorCode: ErrorCode;
  readonly details: Record<string, unknown> | undefined;

  constructor(
    statusCode: number,
    errorCode: ErrorCode,
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "AppError";
    this.statusCode = statusCode;
    this.errorCode = errorCode;
    this.details = details;
  }
}

