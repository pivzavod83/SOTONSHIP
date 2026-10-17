import { registerDecorator } from 'class-validator';
import { sourceWithinPolicy, verificationPolicy } from '../config/verification-policy';

export function IsSourceCode(allowEmpty = false): PropertyDecorator {
  return (target, propertyName) => registerDecorator({
    name: 'isSourceCode', target: target.constructor, propertyName: String(propertyName),
    validator: {
      validate: (value: unknown) => sourceWithinPolicy(value, allowEmpty),
      defaultMessage: () => `Source must be ${allowEmpty ? 'a string' : 'nonempty'} within ${verificationPolicy.maxSourceCharacters} characters and ${verificationPolicy.maxSourceLines} lines.`,
    },
  });
}
