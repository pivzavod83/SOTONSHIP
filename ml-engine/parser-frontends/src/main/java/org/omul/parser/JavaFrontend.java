package org.omul.parser;

import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.IdentifierTree;
import com.sun.source.tree.MemberReferenceTree;
import com.sun.source.tree.MemberSelectTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.Tree;
import com.sun.source.tree.VariableTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.SourcePositions;
import com.sun.source.util.TreePath;
import com.sun.source.util.TreePathScanner;
import com.sun.source.util.Trees;
import java.io.IOException;
import java.io.StringWriter;
import java.net.URI;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.lang.model.element.Element;
import javax.lang.model.element.Modifier;
import javax.lang.model.type.TypeKind;
import javax.lang.model.type.TypeMirror;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.SimpleJavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.StandardLocation;
import javax.tools.ToolProvider;

/** A source-only compiler frontend. It never calls compilation/code generation. */
public final class JavaFrontend {
    private static final int MAX_SOURCE_CHARACTERS = 200_000;
    private static final int MAX_DETAILS = 256;
    private static final int MAX_DIAGNOSTICS = 100;
    private static final List<String> OPTIONS = List.of(
        "--release", "17", "-proc:none", "-implicit:none", "-encoding", "UTF-8",
        "-Xmaxerrs", "100", "-Xmaxwarns", "100"
    );
    private static final Set<Tree.Kind> INTERESTING = Set.of(
        Tree.Kind.CLASS, Tree.Kind.INTERFACE, Tree.Kind.ENUM, Tree.Kind.RECORD,
        Tree.Kind.ANNOTATION_TYPE, Tree.Kind.METHOD, Tree.Kind.VARIABLE,
        Tree.Kind.METHOD_INVOCATION, Tree.Kind.NEW_CLASS, Tree.Kind.NEW_ARRAY,
        Tree.Kind.ASSIGNMENT, Tree.Kind.ARRAY_ACCESS, Tree.Kind.IF, Tree.Kind.SWITCH,
        Tree.Kind.SWITCH_EXPRESSION, Tree.Kind.FOR_LOOP, Tree.Kind.ENHANCED_FOR_LOOP,
        Tree.Kind.WHILE_LOOP, Tree.Kind.DO_WHILE_LOOP, Tree.Kind.TRY, Tree.Kind.CATCH,
        Tree.Kind.THROW, Tree.Kind.RETURN, Tree.Kind.LAMBDA_EXPRESSION,
        Tree.Kind.MEMBER_REFERENCE, Tree.Kind.SYNCHRONIZED
    );

    private JavaFrontend() {}

    public static Map<String, Object> inspect(
        String source, String sourceFormat, String virtualFilename
    ) {
        Map<String, Object> result = baseResult(virtualFilename);
        if (source == null || source.length() > MAX_SOURCE_CHARACTERS) {
            result.put("syntax", phase("ERROR", List.of(problem(
                "frontend.invalid_source", "Source must contain at most "
                    + MAX_SOURCE_CHARACTERS + " characters."))));
            return result;
        }
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            result.put("syntax", phase("UNKNOWN", List.of(problem(
                "frontend.jdk_required", "A full JDK with the javac compiler is required."))));
            return result;
        }

        // The first compiler parse determines the public type's real filename.
        // Submission IDs are often filenames and must not create artificial
        // compiler filename errors. Multiple public types still fail analysis.
        String initialFilename = filename(virtualFilename);
        DiagnosticCollector<JavaFileObject> parseDiagnostics = new DiagnosticCollector<>();
        String actualFilename = initialFilename;
        try (StandardJavaFileManager manager = fileManager(compiler, parseDiagnostics)) {
            JavacTask task = task(compiler, manager, parseDiagnostics, source, initialFilename);
            List<CompilationUnitTree> units = parse(task);
            Map<String, Object> syntax = phase(
                hasErrors(parseDiagnostics) ? "ERROR" : "PARSED", diagnostics(parseDiagnostics, 0));
            AstSummary ast = summarize(units, Trees.instance(task), false);
            syntax.put("astNodes", ast.nodeCount);
            result.put("syntax", syntax);
            result.put("structure", ast.structure());
            for (CompilationUnitTree unit : units) {
                for (Tree declaration : unit.getTypeDecls()) {
                    if (declaration instanceof ClassTree type
                        && type.getModifiers().getFlags().contains(Modifier.PUBLIC)) {
                        actualFilename = type.getSimpleName() + ".java";
                        break;
                    }
                }
            }
            result.put("sourceFilename", actualFilename);
            if (hasErrors(parseDiagnostics)) {
                return result;
            }
        } catch (IOException | RuntimeException exception) {
            result.put("syntax", phase("UNKNOWN", List.of(problem(
                "frontend.parse_failure", safeMessage(exception)))));
            return result;
        }

        DiagnosticCollector<JavaFileObject> semanticDiagnostics = new DiagnosticCollector<>();
        try (StandardJavaFileManager manager = fileManager(compiler, semanticDiagnostics)) {
            JavacTask task = task(compiler, manager, semanticDiagnostics, source, actualFilename);
            List<CompilationUnitTree> units = parse(task);
            int diagnosticsBeforeAnalysis = semanticDiagnostics.getDiagnostics().size();
            if (hasErrors(semanticDiagnostics)) {
                result.put("resolution", phase("UNKNOWN", List.of(problem(
                    "frontend.reparse_failure", "Compiler reparse did not preserve the syntax result."))));
                return result;
            }
            task.analyze(); // Deliberately no task.call(), generate(), annotation processors or execution.
            Trees trees = Trees.instance(task);
            AstSummary ast = summarize(units, trees, true);
            Map<String, Object> resolution = phase(
                hasErrors(semanticDiagnostics) ? "ERROR" : "RESOLVED",
                diagnostics(semanticDiagnostics, diagnosticsBeforeAnalysis));
            resolution.put("resolvedReferences", ast.resolvedReferences);
            resolution.put("unresolvedReferences", ast.unresolvedReferences);
            resolution.put("referenceCount", ast.resolvedReferences + ast.unresolvedReferences);
            resolution.put("bindingComplete", !hasErrors(semanticDiagnostics)
                && ast.unresolvedReferences == 0);
            resolution.put("scope", "Single supplied compilation unit and Java 17 standard library; no external dependencies.");
            result.put("resolution", resolution);
            Map<String, Object> structure = ast.structure();
            structure.put("syntaxAstNodes", ((Map<?, ?>) result.get("syntax")).get("astNodes"));
            structure.put("includesCompilerSynthesizedNodes", true);
            result.put("structure", structure);
        } catch (IOException | RuntimeException exception) {
            result.put("resolution", phase("UNKNOWN", List.of(problem(
                "frontend.analysis_failure", safeMessage(exception)))));
        }
        return result;
    }

    private static Map<String, Object> baseResult(String requestedFilename) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("language", "Java");
        result.put("frontend", Map.of(
            "name", "javac-public-api", "version", Runtime.version().toString(),
            "languageLevel", "Java 17", "annotationProcessing", false,
            "codeGeneration", false, "execution", false));
        result.put("requestedFilename", requestedFilename == null ? "" : requestedFilename);
        result.put("syntax", phase("UNKNOWN", List.of()));
        Map<String, Object> resolution = phase("NOT_ATTEMPTED", List.of());
        resolution.put("resolvedReferences", 0);
        resolution.put("unresolvedReferences", 0);
        resolution.put("bindingComplete", false);
        result.put("resolution", resolution);
        result.put("structure", Map.of("astNodes", 0, "nodeKindCounts", Map.of(),
            "nodes", List.of(), "symbols", List.of(), "declarations", List.of(), "detailsTruncated", false));
        return result;
    }

    private static StandardJavaFileManager fileManager(
        JavaCompiler compiler, DiagnosticCollector<JavaFileObject> diagnostics
    ) throws IOException {
        StandardJavaFileManager manager = compiler.getStandardFileManager(diagnostics, java.util.Locale.ROOT,
            java.nio.charset.StandardCharsets.UTF_8);
        // Resolve only JDK classes and the supplied source, never ambient jars,
        // neighboring source files or generated annotation processors.
        manager.setLocationFromPaths(StandardLocation.CLASS_PATH, List.of());
        manager.setLocationFromPaths(StandardLocation.SOURCE_PATH, List.of());
        manager.setLocationFromPaths(StandardLocation.ANNOTATION_PROCESSOR_PATH, List.of());
        return manager;
    }

    private static JavacTask task(JavaCompiler compiler, StandardJavaFileManager manager,
        DiagnosticCollector<JavaFileObject> diagnostics, String source, String filename) {
        return (JavacTask) compiler.getTask(new StringWriter(), manager, diagnostics,
            OPTIONS, null, List.of(new SourceFile(filename, source)));
    }

    private static List<CompilationUnitTree> parse(JavacTask task) throws IOException {
        List<CompilationUnitTree> units = new ArrayList<>();
        task.parse().forEach(units::add);
        return units;
    }

    private static AstSummary summarize(List<CompilationUnitTree> units, Trees trees, boolean bindings) {
        AstSummary summary = new AstSummary(trees, bindings);
        for (CompilationUnitTree unit : units) {
            summary.unit = unit;
            summary.scan(unit, null);
        }
        return summary;
    }

    private static boolean hasErrors(DiagnosticCollector<JavaFileObject> diagnostics) {
        return diagnostics.getDiagnostics().stream().anyMatch(d -> d.getKind() == Diagnostic.Kind.ERROR);
    }

    private static List<Map<String, Object>> diagnostics(
        DiagnosticCollector<JavaFileObject> collector, int first
    ) {
        List<Map<String, Object>> result = new ArrayList<>();
        List<Diagnostic<? extends JavaFileObject>> entries = collector.getDiagnostics();
        for (int index = first; index < entries.size() && result.size() < MAX_DIAGNOSTICS; index++) {
            Diagnostic<? extends JavaFileObject> diagnostic = entries.get(index);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("code", diagnostic.getCode());
            entry.put("message", bounded(diagnostic.getMessage(java.util.Locale.ROOT), 2048));
            entry.put("line", diagnostic.getLineNumber());
            entry.put("column", diagnostic.getColumnNumber());
            entry.put("severity", diagnostic.getKind().name());
            entry.put("startOffset", diagnostic.getStartPosition());
            entry.put("endOffset", diagnostic.getEndPosition());
            result.add(entry);
        }
        return result;
    }

    private static Map<String, Object> phase(String status, List<Map<String, Object>> diagnostics) {
        Map<String, Object> phase = new LinkedHashMap<>();
        phase.put("status", status);
        phase.put("diagnostics", diagnostics);
        return phase;
    }

    private static Map<String, Object> problem(String code, String message) {
        return Map.of("code", code, "message", message, "line", -1, "column", -1, "severity", "ERROR");
    }

    private static String filename(String supplied) {
        if (supplied == null || supplied.isBlank()) return "Snippet.java";
        String basename = supplied.replace('\\', '/');
        basename = basename.substring(basename.lastIndexOf('/') + 1);
        // A URI-safe name; public type filenames are derived from actual ASTs.
        if (!basename.matches("[\\p{L}\\p{N}_$.-]+\\.java")) return "Snippet.java";
        return basename;
    }

    private static String bounded(String value, int maximum) {
        return value.length() <= maximum ? value : value.substring(0, maximum) + "…";
    }

    private static String safeMessage(Exception exception) {
        String message = exception.getMessage();
        return exception.getClass().getSimpleName() + ": "
            + bounded(message == null ? "Compiler frontend failed." : message, 1024);
    }

    private static final class SourceFile extends SimpleJavaFileObject {
        private final String text;
        SourceFile(String filename, String text) {
            super(URI.create("string:///" + filename), Kind.SOURCE);
            this.text = text;
        }
        @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) { return text; }
    }

    private static final class AstSummary extends TreePathScanner<Void, Void> {
        final Trees trees;
        final SourcePositions positions;
        final boolean bindings;
        CompilationUnitTree unit;
        int nodeCount;
        int resolvedReferences;
        int unresolvedReferences;
        int interestingNodes;
        int symbolCount;
        int declarationCount;
        final Map<String, Integer> kinds = new LinkedHashMap<>();
        final List<Map<String, Object>> nodes = new ArrayList<>();
        final List<Map<String, Object>> symbols = new ArrayList<>();
        final List<Map<String, Object>> declarations = new ArrayList<>();
        final Map<Element, String> symbolIds = new IdentityHashMap<>();

        AstSummary(Trees trees, boolean bindings) {
            this.trees = trees;
            this.positions = trees.getSourcePositions();
            this.bindings = bindings;
        }

        @Override public Void scan(Tree tree, Void unused) {
            if (tree == null) return null;
            nodeCount++;
            kinds.merge(tree.getKind().name(), 1, Integer::sum);
            if (INTERESTING.contains(tree.getKind())) {
                interestingNodes++;
                if (nodes.size() < MAX_DETAILS) {
                    Map<String, Object> node = span(tree);
                    node.put("kind", tree.getKind().name());
                    nodes.add(node);
                }
            }
            return super.scan(tree, unused);
        }

        @Override public Void visitIdentifier(IdentifierTree tree, Void unused) {
            reference(tree);
            return super.visitIdentifier(tree, unused);
        }

        @Override public Void visitClass(ClassTree tree, Void unused) {
            declaration(tree);
            return super.visitClass(tree, unused);
        }

        @Override public Void visitMethod(MethodTree tree, Void unused) {
            declaration(tree);
            return super.visitMethod(tree, unused);
        }

        @Override public Void visitVariable(VariableTree tree, Void unused) {
            declaration(tree);
            return super.visitVariable(tree, unused);
        }

        @Override public Void visitMemberSelect(MemberSelectTree tree, Void unused) {
            // The '*' in an on-demand import is syntax, not an unresolved
            // member reference. Its package/type qualifier is still visited.
            if (!tree.getIdentifier().contentEquals("*")) reference(tree);
            return super.visitMemberSelect(tree, unused);
        }

        @Override public Void visitMemberReference(MemberReferenceTree tree, Void unused) {
            reference(tree);
            return super.visitMemberReference(tree, unused);
        }

        private void reference(Tree tree) {
            if (!bindings) return;
            // javac inserts default constructors and super() calls during
            // attribution. They have no complete source span and must not
            // inflate counts of references present in the supplied program.
            if (positions.getStartPosition(unit, tree) < 0
                || positions.getEndPosition(unit, tree) < 0) return;
            TreePath path = getCurrentPath();
            Element element = trees.getElement(path);
            TypeMirror type = trees.getTypeMirror(path);
            boolean bound = element != null && (type == null || type.getKind() != TypeKind.ERROR);
            if (bound) resolvedReferences++; else unresolvedReferences++;
            symbolCount++;
            if (symbols.size() >= MAX_DETAILS) return;
            Map<String, Object> symbol = span(tree);
            symbol.put("reference", bounded(tree.toString(), 256));
            symbol.put("resolved", bound);
            bindingDetails(symbol, element, type);
            symbols.add(symbol);
        }

        private void declaration(Tree tree) {
            if (!bindings || positions.getStartPosition(unit, tree) < 0
                || positions.getEndPosition(unit, tree) < 0) return;
            declarationCount++;
            if (declarations.size() >= MAX_DETAILS) return;
            Map<String, Object> declaration = span(tree);
            declaration.put("kind", tree.getKind().name());
            TreePath path = getCurrentPath();
            bindingDetails(declaration, trees.getElement(path), trees.getTypeMirror(path));
            declarations.add(declaration);
        }

        private void bindingDetails(Map<String, Object> detail, Element element, TypeMirror type) {
            // IDs are scoped to this inspection, and connect a declaration to
            // its uses even when shadowed variables share the same spelling.
            detail.put("symbolId", element == null ? "" : symbolIds.computeIfAbsent(element,
                ignored -> "symbol-" + (symbolIds.size() + 1)));
            detail.put("elementKind", element == null ? "UNKNOWN" : element.getKind().name());
            detail.put("name", element == null ? "" : bounded(element.toString(), 256));
            Element owner = element == null ? null : element.getEnclosingElement();
            detail.put("owner", owner == null ? "" : bounded(owner.toString(), 256));
            detail.put("type", type == null ? "UNKNOWN" : bounded(type.toString(), 256));
        }

        private Map<String, Object> span(Tree tree) {
            Map<String, Object> result = new LinkedHashMap<>();
            long start = positions.getStartPosition(unit, tree);
            long end = positions.getEndPosition(unit, tree);
            result.put("startOffset", start);
            result.put("endOffset", end);
            result.put("compilerSynthesized", start < 0 || end < 0);
            result.put("startLine", start < 0 ? -1L : unit.getLineMap().getLineNumber(start));
            result.put("startColumn", start < 0 ? -1L : unit.getLineMap().getColumnNumber(start));
            long finalCharacter = end <= 0 ? -1 : end - 1;
            result.put("endLine", finalCharacter < 0 ? -1L : unit.getLineMap().getLineNumber(finalCharacter));
            result.put("endColumn", finalCharacter < 0 ? -1L : unit.getLineMap().getColumnNumber(finalCharacter));
            return result;
        }

        Map<String, Object> structure() {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("astNodes", nodeCount);
            result.put("nodeKindCounts", kinds);
            result.put("nodes", nodes);
            result.put("symbols", symbols);
            result.put("declarations", declarations);
            result.put("symbolIdentityScope", "Within this inspection only; compiler element identity, not identifier spelling.");
            result.put("detailsTruncated", interestingNodes > nodes.size() || symbolCount > symbols.size()
                || declarationCount > declarations.size());
            result.put("detailLimit", MAX_DETAILS);
            return result;
        }
    }
}
