import { VerificationRevision } from '../entities/verification-revision';
import { VerificationId } from '../value-objects/verification-id';
export const VERIFICATION_HISTORY = 'IVerificationHistoryRepository';
export interface IVerificationHistoryRepository { findByVerification(id: VerificationId): Promise<VerificationRevision[]>; }
