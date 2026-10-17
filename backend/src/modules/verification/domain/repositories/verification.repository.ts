import { VerificationRun } from '../entities/verification-run';
import { VerificationId } from '../value-objects/verification-id';

export const VERIFICATION_REPOSITORY = 'IVerificationRepository';
export interface IVerificationRepository {
  findAll(): Promise<VerificationRun[]>;
  findPage(limit: number, offset: number): Promise<VerificationRun[]>;
  findById(id: VerificationId): Promise<VerificationRun | null>;
  save(run: VerificationRun): Promise<VerificationRun>;
}
