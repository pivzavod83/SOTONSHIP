import { readdirSync, readFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import ts from 'typescript';

const source = resolve(__dirname, '../src');
function files(path: string): string[] {
  return readdirSync(path, { withFileTypes: true }).flatMap((entry) => entry.isDirectory()
    ? files(join(path, entry.name)) : entry.name.endsWith('.ts') ? [join(path, entry.name)] : []);
}
function imports(path: string): string[] {
  return ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true).statements
    .filter(ts.isImportDeclaration).map((entry) => (entry.moduleSpecifier as ts.StringLiteral).text);
}

describe('Layer boundaries', () => {
  const paths = files(join(source, 'modules'));
  it('keeps all domain imports free of frameworks, persistence, HTTP and application dependencies', () => {
    const violations = paths.filter((path) => path.includes('/domain/')).flatMap((path) => imports(path)
      .filter((name) => name.startsWith('@') || /\/(infrastructure|application|presentation|entities\/.*\.entity)(\/|$)/.test(name))
      .map((name) => `${relative(source, path)} -> ${name}`));
    expect(violations).toEqual([]);
  });
  it('keeps application and HTTP layers dependent on domain interfaces rather than persistence entities', () => {
    const violations = paths.filter((path) => /\/(application|presentation)\//.test(path)).flatMap((path) => imports(path)
      .filter((name) => name.startsWith('@mikro-orm/') || name.includes('/infrastructure/') || name.endsWith('.entity'))
      .map((name) => `${relative(source, path)} -> ${name}`));
    expect(violations).toEqual([]);
  });
  it('keeps controllers free of repositories, entity managers, and direct use-case services', () => {
    const violations = paths.filter((path) => path.endsWith('.controller.ts')).flatMap((path) => imports(path)
      .filter((name) => /repository|\.service|\/domain\/entities\//.test(name))
      .map((name) => `${relative(source, path)} -> ${name}`));
    expect(violations).toEqual([]);
  });
});
