export class InfrastructureException extends Error {
  constructor(message: string, readonly code = 'infrastructure.unavailable', options?: ErrorOptions) {
    super(message, options);
    this.name = 'InfrastructureException';
  }
}
