package org.omul.parser;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.Test;

/** Compiler phase regressions; assertions can also be invoked by main(). */
public final class JavaFrontendTest {
    @Test public void compilerPhasesAndSpansRemainDistinct() {
        main(new String[0]);
    }

    @Test public void shadowedVariablesHaveDifferentCompilerIdentities() {
        Map<String, Object> result = JavaFrontend.inspect(
            "public class Main { int value; int f(int value) { return this.value + value; } }",
            "FREE", "Main.java");
        Map<?, ?> structure = (Map<?, ?>) result.get("structure");
        Set<?> declarations = ((List<?>) structure.get("declarations")).stream()
            .map(value -> (Map<?, ?>) value).filter(value -> "value".equals(value.get("name")))
            .map(value -> value.get("symbolId")).collect(Collectors.toSet());
        Set<?> references = ((List<?>) structure.get("symbols")).stream()
            .map(value -> (Map<?, ?>) value).filter(value -> "value".equals(value.get("name")))
            .map(value -> value.get("symbolId")).collect(Collectors.toSet());
        check(declarations.size() == 2, "Shadowed declarations were conflated.");
        check(declarations.equals(references), "Source references did not bind to their declarations.");
    }

    @Test public void semanticDiagnosticsHaveSourceLocations() {
        Map<String, Object> result = JavaFrontend.inspect(
            "class Main {\n int f() { return unknown; }\n}", "FREE", "Main.java");
        Map<?, ?> resolution = (Map<?, ?>) result.get("resolution");
        List<?> diagnostics = (List<?>) resolution.get("diagnostics");
        check(diagnostics.stream().map(value -> (Map<?, ?>) value).anyMatch(value ->
            ((Number) value.get("line")).intValue() == 2
            && ((Number) value.get("column")).intValue() > 0), "Diagnostic source location is missing.");
        check(((List<?>) ((Map<?, ?>) result.get("syntax")).get("diagnostics")).isEmpty(),
            "Type/name error leaked into syntax diagnostics.");
    }

    public static void main(String[] arguments) {
        assertPhases("import java.util.Arrays; public class Main {"
            + "static int sum(int[] xs) { return Arrays.stream(xs).sum(); }"
            + "static long sum(long a, long b) { return a + b; }"
            + "public static void main(String[] args) {"
            + "java.util.function.IntUnaryOperator f = x -> x + 1;"
            + "System.out.println(f.applyAsInt(sum(new int[]{1,2}))); }}",
            "PARSED", "RESOLVED");
        assertPhases("public class Other { int f() { return missing; } }", "PARSED", "ERROR");
        assertPhases("public class Main { int amount = \"hello\"; }", "PARSED", "ERROR");
        assertPhases("public class Main { int f( { return 1; } }", "ERROR", "NOT_ATTEMPTED");
        assertPhases("public record Main(int amount) { int twice() { return amount * 2; } }",
            "PARSED", "RESOLVED");
        assertPhases("import imaginary.Library; public class Main { Library value; }", "PARSED", "ERROR");
        assertPhases("import java.util.*; public class Main { List<String> names = new ArrayList<>(); }",
            "PARSED", "RESOLVED");
        assertPhases("public class Main { static { System.setProperty(\"omul.frontend.executed\", \"yes\"); } }",
            "PARSED", "RESOLVED");
        check(System.getProperty("omul.frontend.executed") == null, "Supplied source was executed.");
        assertPhases("public class One {} public class Two {}", "PARSED", "ERROR");
        Map<String, Object> renamed = JavaFrontend.inspect(
            "public class Main { int[] values = {1, 2}; }", "FREE", "s0000001.java");
        check("Main.java".equals(renamed.get("sourceFilename")), "Public filename was not derived.");
        Map<?, ?> structure = (Map<?, ?>) renamed.get("structure");
        check(((Map<?, ?>) structure.get("nodeKindCounts")).containsKey("NEW_ARRAY"),
            "Array AST structure is missing.");
        check(((List<?>) structure.get("nodes")).stream().anyMatch(value ->
            Long.valueOf(1).equals(((Map<?, ?>) value).get("startLine"))), "Source spans are missing.");
        Map<String, Object> mismatch = JavaFrontend.inspect(
            "class Main { int f() { return missing; } }", "FREE", "Main.java");
        check(((Number) ((Map<?, ?>) mismatch.get("resolution")).get("unresolvedReferences")).intValue() > 0,
            "Undefined reference was not counted.");
        Map<String, Object> large = JavaFrontend.inspect(" ".repeat(200_001), "FREE", "Main.java");
        check("ERROR".equals(((Map<?, ?>) large.get("syntax")).get("status")), "Size cap was not enforced.");
        System.out.println("JavaFrontend: 13 regression checks passed.");
    }

    private static void assertPhases(String source, String syntax, String resolution) {
        Map<String, Object> result = JavaFrontend.inspect(source, "FREE", "submission.java");
        check(syntax.equals(((Map<?, ?>) result.get("syntax")).get("status")),
            "Syntax mismatch: " + result);
        check(resolution.equals(((Map<?, ?>) result.get("resolution")).get("status")),
            "Resolution mismatch: " + result);
        if ("RESOLVED".equals(resolution)) {
            check(Boolean.TRUE.equals(((Map<?, ?>) result.get("resolution")).get("bindingComplete")),
                "Valid standard-library source had unresolved references: " + result);
        }
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
