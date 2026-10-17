/** Framework-free exceptions are safe for domain imports. */
export class DomainException extends Error {
  constructor(message: string, readonly code = 'domain.validation_failed') {
    super(message);
    this.name = 'DomainException';
  }
}
