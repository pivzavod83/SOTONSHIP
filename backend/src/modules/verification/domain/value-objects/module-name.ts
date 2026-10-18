import { DomainException } from '../../../../common/exceptions/domain.exception';

export class ModuleName {
  readonly value: string;
  constructor(value: string) {
    this.value = value.trim();
    if (!this.value || this.value.length > 160 || /[\x00-\x1f/\\]/.test(this.value)) {
      throw new DomainException('Module name must be a safe name of 1–160 characters.');
    }
  }
}
