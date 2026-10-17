export class ApplicationException extends Error {
  constructor(message: string, readonly code = 'application.failed', readonly statusCode = 422) {
    super(message);
    this.name = 'ApplicationException';
  }
}
